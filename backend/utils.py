import os
import json
import logging
import requests
import dataclasses
from datetime import datetime, timedelta
import re
from urllib.parse import unquote, urlparse
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

DEBUG = os.environ.get("DEBUG", "false")
if DEBUG.lower() == "true":
    logging.basicConfig(level=logging.DEBUG)

AZURE_SEARCH_PERMITTED_GROUPS_COLUMN = os.environ.get(
    "AZURE_SEARCH_PERMITTED_GROUPS_COLUMN"
)

STANDARD_NO_DATA_RESPONSE = "The requested information is not found in the retrieved data. Please try another query or topic."
NO_DATA_FOUND_RESPONSE = os.environ.get("NO_DATA_FOUND_RESPONSE", STANDARD_NO_DATA_RESPONSE)
BLOB_CREDENTIAL = os.environ.get("BLOB_CREDENTIAL")
BLOB_ACCOUNT = os.environ.get("BLOB_ACCOUNT")

class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


async def format_as_ndjson(r):
    try:
        async for event in r:
            yield json.dumps(event, cls=JSONEncoder) + "\n"
    except Exception as error:
        logging.exception("Exception while generating response stream: %s", error)
        yield json.dumps({"error": str(error)})


def preprocess_response(content):
    '''
    Preprocessing of bot response before it is returned. Following preprocessing is performed:
    - Rewrite message returned when AI Search is unable to find data
    '''
    content = content.replace("The requested information is not found in the retrieved data. Please try another query or topic.", NO_DATA_FOUND_RESPONSE).replace(r"\u20ac","€")
    return content


def parse_multi_columns(columns: str) -> list:
    if "|" in columns:
        return columns.split("|")
    else:
        return columns.split(",")


def fetchUserGroups(userToken, nextLink=None):
    # Recursively fetch group membership
    if nextLink:
        endpoint = nextLink
    else:
        endpoint = "https://graph.microsoft.com/v1.0/me/transitiveMemberOf?$select=id"

    headers = {"Authorization": "bearer " + userToken}
    try:
        r = requests.get(endpoint, headers=headers)
        if r.status_code != 200:
            logging.error(f"Error fetching user groups: {r.status_code} {r.text}")
            return []

        r = r.json()
        if "@odata.nextLink" in r:
            nextLinkData = fetchUserGroups(userToken, r["@odata.nextLink"])
            r["value"].extend(nextLinkData)

        return r["value"]
    except Exception as e:
        logging.error(f"Exception in fetchUserGroups: {e}")
        return []

def generateUserFilterString(userToken):
    # Get list of groups user is a member of
    userGroups = fetchUserGroups(userToken)

    # Construct filter string
    if not userGroups:
        logging.debug("No user groups found")

    group_ids = ", ".join([obj["id"] for obj in userGroups])
    return f"{AZURE_SEARCH_PERMITTED_GROUPS_COLUMN}/any(g:search.in(g, '{group_ids}'))"

def create_filter_string(filter_array, filter_name):
    if filter_array:
        string = ' or '.join(f"({filter_name} eq '{item}')" for item in filter_array)
        return f"({string})"
    return ""

def generateFilterString(message):
    # Extract the last request message filters
    types_filter_array = message["types_filter"] 
    rules_filter_array = message["rules_filter"] 
    parts_filter_array = message["parts_filter"] 

    # Create filter strings for each filter type
    types_filter_string = create_filter_string(types_filter_array, "type")
    rules_filter_string = create_filter_string(rules_filter_array, "rule")
    parts_filter_string = create_filter_string(parts_filter_array, "part")

    # Combine the non-empty filter strings with ' and '
    filter_conditions = [condition for condition in [types_filter_string, rules_filter_string, parts_filter_string] if condition]
    filter_string = ' and '.join(filter_conditions) if filter_conditions else ""
    return filter_string

def remove_SAS_token(url):
    parsed_url = urlparse(url)
    url_without_query = parsed_url.scheme + "://" + parsed_url.netloc + parsed_url.path
    return url_without_query

def generate_SAS(url):
    container, blob = split_url(url)
    blob_service_client =BlobServiceClient(BLOB_ACCOUNT, credential=BLOB_CREDENTIAL)
    blob_client = blob_service_client.get_blob_client(container=container, blob=blob)

    sas_token_expiry_time = datetime.utcnow() + timedelta(hours=1)  # 1 hour from now

    sas_token = generate_blob_sas(
        account_name=blob_client.account_name,
        container_name=blob_client.container_name,
        blob_name=blob_client.blob_name,
        account_key=BLOB_CREDENTIAL,
        permission=BlobSasPermissions(read=True),
        expiry=sas_token_expiry_time
    )

    return sas_token

def split_url(url):
    url_decoded = unquote(url)
    if url_decoded.endswith('/'):
        url_decoded = url_decoded[:-1]
    pattern = fr"{BLOB_ACCOUNT}/([^/]+)/(.+)"
    match = re.search(pattern, url)
    if match:
        container = match.group(1)
        blob = match.group(2)
        return container, blob
    else:
        return None, None

def append_SAS_to_image_link(content):
    pattern = r'!\[(.*?)\]\((.*?)\)'
    def url_replacer(match):
        original_url = match.group(2)
        generated_string = generate_SAS(original_url)
        return f"![{match.group(1)}]({original_url}?{generated_string})"
    replaced_text = re.sub(pattern, url_replacer, content)
    return replaced_text

def remove_SAS_from_image_link(content):    
    pattern = r'!\[(.*?)\]\((.*?)\)'
    def url_replacer(match):
        original_url = match.group(2)
        url_cleaned = remove_SAS_token(original_url)
        return f"![{match.group(1)}]({url_cleaned})"
    replaced_text = re.sub(pattern, url_replacer, content)
    return replaced_text

def format_non_streaming_response(chatCompletion, history_metadata, apim_request_id):
    response_obj = {
        "id": chatCompletion.id,
        "model": chatCompletion.model,
        "created": chatCompletion.created,
        "object": chatCompletion.object,
        "choices": [{"messages": []}],
        "history_metadata": history_metadata,
        "apim-request-id": apim_request_id,
    }

    if len(chatCompletion.choices) > 0:
        message = chatCompletion.choices[0].message
        if message:
            if hasattr(message, "context"):
                content = message.context
                for i, chunk in enumerate(content["citations"]):
                    content["citations"][i]["url"]=chunk["url"]+"?"+generate_SAS(chunk["url"])
                response_obj["choices"][0]["messages"].append(
                    {
                        "role": "tool",
                        "content": json.dumps(content),
                    }
                )
            response_obj["choices"][0]["messages"].append(
                {
                    "role": "assistant",
                    "content": preprocess_response(append_SAS_to_image_link(message.content)),
                }
            )
            return response_obj

    return {}

def format_stream_response(chatCompletionChunk, history_metadata, apim_request_id):
    response_obj = {
        "id": chatCompletionChunk.id,
        "model": chatCompletionChunk.model,
        "created": chatCompletionChunk.created,
        "object": chatCompletionChunk.object,
        "choices": [{"messages": []}],
        "history_metadata": history_metadata,
        "apim-request-id": apim_request_id,
    }

    if len(chatCompletionChunk.choices) > 0:
        delta = chatCompletionChunk.choices[0].delta
        if delta:
            if hasattr(delta, "context"):
                content = delta.context
                for i, chunk in enumerate(content["citations"]):
                    content["citations"][i]["url"]=chunk["url"]+"?"+generate_SAS(chunk["url"])
                messageObj = {"role": "tool", "content": json.dumps(content)}
                response_obj["choices"][0]["messages"].append(messageObj)
                return response_obj
            if delta.role == "assistant" and hasattr(delta, "context"):
                messageObj = {
                    "role": "assistant",
                    "context": delta.context,
                }
                response_obj["choices"][0]["messages"].append(messageObj)
                return response_obj
            else:
                if delta.content:
                    messageObj = {
                        "role": "assistant",
                        "content": delta.content,
                    }
                    response_obj["choices"][0]["messages"].append(messageObj)
                    return response_obj

    return {}