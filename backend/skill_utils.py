import logging
import os
import re
from io import BytesIO
from PIL import Image
from docx import Document

from azure.storage.blob import ContentSettings
from azure.core.exceptions import ResourceNotFoundError

from backend.utils import (
    split_url
)

# Document Intelligence Configuration
DOCUMENT_INTELLIGENCE_ENDPOINT = os.environ.get("DOCUMENT_INTELLIGENCE_ENDPOINT")
DOCUMENT_INTELLIGENCE_KEY = os.environ.get("DOCUMENT_INTELLIGENCE_KEY")
# Blob Storage
BLOB_CREDENTIAL = os.environ.get("BLOB_CREDENTIAL")
BLOB_ACCOUNT = os.environ.get("BLOB_ACCOUNT")
FORMULA_IMAGE_CONTAINER = os.environ.get("CONTAINER_FORMULA_IMAGE")
LOCAL_TEMP_DIR = os.environ.get("LOCAL_TEMP_DIR")
 
def blob_exists(blob_service_client, container, blob_name):
    blob_client = blob_service_client.get_blob_client(container=container, blob=blob_name)
    try:
        blob_client.get_blob_properties()
        return True
    except ResourceNotFoundError:
        return False

def download_file(blob_service_client, url):
    blob_container, blob_name = split_url(url)
    local_filepath = f'{LOCAL_TEMP_DIR}/{blob_name}'
    blob_client = blob_service_client.get_blob_client(container=blob_container, blob=blob_name)

    try:
        with open(local_filepath, "wb") as downloaded_file:
            download_stream = blob_client.download_blob()
            downloaded_file.write(download_stream.readall())
        logging.info("Downloaded Word Document")
    except Exception as e:
        logging.error(f"An error occurred while downloading the file: {e}")
        raise  # Re-raise the exception to be handled by the caller

    return local_filepath
 
def extract_text_with_subscript(doc_path):
    doc = Document(doc_path)
    extracted_text = ""
    in_subscript = False  # Keep track of whether we are currently in a subscript block
 
    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            if run.font.subscript:
                if not in_subscript:
                    # Starting a new subscript block
                    extracted_text += "<sub>"
                    in_subscript = True
                # Append the subscript text
                extracted_text += run.text
            else:
                if in_subscript:
                    # Closing the current subscript block
                    extracted_text += "</sub>"
                    in_subscript = False
                # Append the non-subscript text
                extracted_text += run.text
        # Close any unclosed subscript tags at the end of a paragraph
        if in_subscript:
            extracted_text += "</sub>"
            in_subscript = False
        extracted_text += "\n"  # New line after each paragraph
    print("Extracted subscript from word document.")
    return extracted_text

############## Clean Text ##################
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
 
class DocumentWord:
    def __init__(self, content, polygon, span, confidence):
        self.content = content
        self.polygon = polygon
        self.span = span
        self.confidence = confidence
 
def get_aabb(polygon):
    """Given a polygon (list of Points), returns its axis-aligned bounding box."""
    min_x = min(point.x for point in polygon)
    max_x = max(point.x for point in polygon)
    min_y = min(point.y for point in polygon)
    max_y = max(point.y for point in polygon)
    return [Point(min_x, min_y), Point(max_x, max_y)]
 
def is_overlapping(aabb_a, aabb_b):
    """Checks if two AABBs overlap."""
    # Check if one AABB is to the left of the other
    if aabb_a[1].x < aabb_b[0].x or aabb_b[1].x < aabb_a[0].x:
        return False
    # Check if one AABB is above the other
    if aabb_a[1].y < aabb_b[0].y or aabb_b[1].y < aabb_a[0].y:
        return False
    return True
 
def overwrite_words_with_formulas(words, formulas):
    updated_words = words[:]  # Create a copy of the words list to modify
    for formula in formulas:
        formula_aabb = get_aabb(formula.polygon)
        overlapping_indices = []
 
        # Find indices of words that overlap with the formula
        for i, word in enumerate(updated_words):
            word_aabb = get_aabb(word.polygon)
            if is_overlapping(formula_aabb, word_aabb):
                overlapping_indices.append(i)
        if overlapping_indices:
            # Sort indices in reverse order to keep them valid while deleting
            overlapping_indices.sort(reverse=True)
            # Remove overlapping words
            for index in overlapping_indices:
                del updated_words[index]
            # Create a new DocumentWord for the formula
            formula_word = DocumentWord(content=formula.content, polygon=formula.polygon, span=formula.span, confidence=formula.confidence)
            # Insert the formula word at the position of the first removed word
            updated_words.insert(overlapping_indices[-1], formula_word)
    return updated_words
 
def fix_greek_letters(docx_text, ocr_text):
    # Define a mapping of Greek letters to their commonly mistaken Latin counterparts
    greek_to_latin_mapping = {'β': 'B', 'γ': 'y', 'φ':'o', 'α':'a', 'Ω':'Q'}
   
    # Regular expression to find Greek letters
    greek_letter_regex = r'[\u0370-\u03FF]'
   
    # Function to extract snippets around Greek letters
    def extract_snippets(text, regex, snippet_length=3):
        snippets = []
        for match in re.finditer(regex, text):
            start = max(match.start() - snippet_length, 0)
            end = min(match.end() + snippet_length, len(text))
            snippet = text[start:end]
            snippets.append((match.group(), snippet, start, end))
        return snippets
   
    # Function to replace Latin characters with Greek letters based on snippets
    def replace_in_ocr(ocr_text, snippets, mapping):
        for greek_letter, snippet, start, end in snippets:
            latin_char = mapping[greek_letter]
            # Create a pattern to match the snippet in the OCR text, allowing for some variation
            pattern = re.escape(snippet).replace(greek_letter, latin_char)
            # Find the snippet in the OCR text
            match = re.search(pattern, ocr_text)
            if match:
                # Replace the Latin character with the Greek letter
                ocr_text = ocr_text[:match.start()] + ocr_text[match.start():match.end()].replace(latin_char, greek_letter, 1) + ocr_text[match.end():]
        return ocr_text
   
    # Extract snippets around Greek letters in the docx_text
    snippets = extract_snippets(docx_text, greek_letter_regex)
    # Replace Latin characters with Greek letters in the OCR text
    corrected_ocr_text = replace_in_ocr(ocr_text, snippets, greek_to_latin_mapping)
 
    return corrected_ocr_text
 
def insert_subscripts(docx_text, ocr_text):
    # Common OCR inaccuracies mapping
    ocr_inaccuracies = {
        'γ': 'y',
        'v': 'w',
        'l': 'i',
        'l': 'I',
    }
    
    # Step 1: Identify words with subscripts in the python-docx text
    subscript_pattern = r'(\w+)<sub>(\w+)</sub>'
    subscript_matches = re.findall(subscript_pattern, docx_text)
   
    # Step 2: Generate OCR variations and create a mapping to the correct version
    def generate_ocr_variations(word, inaccuracies):
        variations = [word]
        for original, replacement in inaccuracies.items():
            new_variations = []
            for variation in variations:
                if original in variation:
                    new_variations.append(variation.replace(original, replacement))
            variations.extend(new_variations)
        return variations
   
    mapping = {}
    for match in subscript_matches:
        correct_word = f"{match[0]}<sub>{match[1]}</sub>"
        base_word = match[0] + match[1]
        for variation in generate_ocr_variations(base_word, ocr_inaccuracies):
            mapping[variation] = correct_word
   
    # Step 3: Replace words in the OCR text using the mapping
    for ocr_variation, correct_word in mapping.items():
        ocr_text = re.sub(r'\b' + re.escape(ocr_variation) + r'\b', correct_word, ocr_text)
 
    return ocr_text
 
def clean_ocr_text(docx_text, ocr_text):
    ocr_with_greek_letters = fix_greek_letters(docx_text, ocr_text)
    print("Added greek characters to OCR text")
    cleaned_ocr_text = insert_subscripts(docx_text, ocr_with_greek_letters)
    print("Added subscript tags to OCR text")
    return cleaned_ocr_text

def screenshot_formula(blob_service_client, image_bytes, formula_filepath, points):
    image = Image.open(BytesIO(image_bytes))
    x1, y1 = points[0].x, points[0].y
    x2, y2 = points[2].x, points[2].y
    x1 -= 10
    x2 += 10
    y2 += 10
    cropped_image = image.crop((x1, y1, x2, y2))
    image_stream = BytesIO()
    cropped_image.save(image_stream, format='PNG')
    image_stream.seek(0)
    content_settings = ContentSettings(content_type="image/png")
    blob_client = blob_service_client.get_blob_client(container=FORMULA_IMAGE_CONTAINER, blob=formula_filepath)
    blob_client.upload_blob(image_stream.getvalue(), content_settings=content_settings, blob_type="BlockBlob", overwrite=True)
 

 
def is_complex_formula(formula):
    # Define patterns that indicate a complex formula
    complex_patterns = [
        r'\\sum',          # Summation
        r'\\frac',         # Fraction
        r'\\left',         # Left delimiter
        r'\\right',        # Right delimiter
        r'\\times',        # Multiplication
        r'\\partial',      # Partial derivative
        '='
        # Add more patterns here as needed
    ]
    # Check if any of the complex patterns are present in the formula
    for pattern in complex_patterns:
        if re.search(pattern, formula):
            return True
    # If none of the complex patterns are found, it's a simple formula
    return False

def get_relevant_formula_for_normalised_images(result, identifier):
    if not result.pages[0].formulas:
        return []
    return [
        DocumentWord(content=f'formula_{identifier}_{formula_id}.png', polygon=f.polygon, span=f.span, confidence=f.confidence)
        for formula_id, f in enumerate(result.pages[0].formulas)
        # Filter formulas that have a significant width
        if is_complex_formula(f.value)
    ]