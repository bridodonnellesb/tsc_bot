import copy
import json
import os
import logging
import uuid
from itertools import combinations
from dotenv import load_dotenv
import httpx
import requests
import base64
import time
import backoff 
from datetime import datetime, timezone
from collections import namedtuple
from quart import (
    Blueprint,
    Quart,
    jsonify,
    make_response,
    request,
    send_from_directory,
    render_template,
)
from docx import Document
import xml.etree.ElementTree as ET
from PIL import Image
from math import sqrt
import re
from io import BytesIO
from pdf2image import convert_from_path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import HttpResponseError
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient, AnalysisFeature
from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

from openai import AsyncAzureOpenAI

from backend.auth.auth_utils import get_authenticated_user_details
from backend.history.cosmosdbservice import CosmosConversationClient



from backend.utils import (
    format_as_ndjson,
    format_stream_response,
    remove_SAS_token,
    generateFilterString,
    remove_SAS_from_image_link,
    parse_multi_columns,
    format_non_streaming_response,
    convert_to_pf_format,
    format_pf_non_streaming_response,
    split_url
)

from backend.skill_utils import (
    get_relevant_formula,
    screenshot_formula,
    overwrite_words_with_formulas,
    clean_ocr_text,
    download_file,
    # convert_docx_to_images
    extract_text_with_subscript,
    upload_images_to_blob_storage,
    docx_to_pdf_name
)

bp = Blueprint("routes", __name__, static_folder="static", template_folder="static")

# Current minimum Azure OpenAI version supported
MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION = "2024-02-15-preview"

load_dotenv()

# UI configuration (optional)
UI_TITLE = os.environ.get("UI_TITLE") or "Contoso"
UI_LOGO = os.environ.get("UI_LOGO")
UI_CHAT_LOGO = os.environ.get("UI_CHAT_LOGO")
UI_CHAT_TITLE = os.environ.get("UI_CHAT_TITLE") or "Start chatting"
UI_CHAT_DESCRIPTION = (
    os.environ.get("UI_CHAT_DESCRIPTION")
    or "This chatbot is configured to answer your questions"
)
UI_FAVICON = "ESB.ico"
UI_SHOW_SHARE_BUTTON = os.environ.get("UI_SHOW_SHARE_BUTTON", "true").lower() == "true"

# Document Intelligence Configuration
DOCUMENT_INTELLIGENCE_ENDPOINT = os.environ.get("DOCUMENT_INTELLIGENCE_ENDPOINT")
DOCUMENT_INTELLIGENCE_KEY = os.environ.get("DOCUMENT_INTELLIGENCE_KEY")
# Blob Storage
BLOB_CREDENTIAL = os.environ.get("BLOB_CREDENTIAL")
BLOB_ACCOUNT = os.environ.get("BLOB_ACCOUNT")
FORMULA_IMAGE_CONTAINER = os.environ.get("FORMULA_IMAGE_CONTAINER")
PAGE_IMAGE_CONTAINER = os.environ.get("PAGE_IMAGE_CONTAINER")
PDF_CONTAINER = os.environ.get("PDF_CONTAINER")
LOCAL_TEMP_DIR = os.environ.get("LOCAL_TEMP_DIR")

def create_app():
    app = Quart(__name__)
    app.register_blueprint(bp)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    return app


@bp.route("/")
async def index():
    return await render_template("index.html", title=UI_TITLE, favicon=UI_FAVICON)


@bp.route("/favicon.ico")
async def favicon():
    return await bp.send_static_file("favicon.ico")


@bp.route("/assets/<path:path>")
async def assets(path):
    return await send_from_directory("static/assets", path)


# Debug settings
DEBUG = os.environ.get("DEBUG", "false")
if DEBUG.lower() == "true":
    logging.basicConfig(level=logging.DEBUG)

USER_AGENT = "GitHubSampleWebApp/AsyncAzureOpenAI/1.0.0"

# On Your Data Settings
DATASOURCE_TYPE = os.environ.get("DATASOURCE_TYPE", "AzureCognitiveSearch")
SEARCH_TOP_K = os.environ.get("SEARCH_TOP_K", 5)
SEARCH_STRICTNESS = os.environ.get("SEARCH_STRICTNESS", 3)
SEARCH_ENABLE_IN_DOMAIN = os.environ.get("SEARCH_ENABLE_IN_DOMAIN", "true")

# ACS Integration Settings
AZURE_SEARCH_SERVICE = os.environ.get("AZURE_SEARCH_SERVICE")
AZURE_SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX")
AZURE_SEARCH_KEY = os.environ.get("AZURE_SEARCH_KEY", None)
AZURE_SEARCH_USE_SEMANTIC_SEARCH = os.environ.get(
    "AZURE_SEARCH_USE_SEMANTIC_SEARCH", "false"
)
AZURE_SEARCH_SEMANTIC_SEARCH_CONFIG = os.environ.get(
    "AZURE_SEARCH_SEMANTIC_SEARCH_CONFIG", "default"
)
AZURE_SEARCH_TOP_K = os.environ.get("AZURE_SEARCH_TOP_K", SEARCH_TOP_K)
AZURE_SEARCH_ENABLE_IN_DOMAIN = os.environ.get(
    "AZURE_SEARCH_ENABLE_IN_DOMAIN", SEARCH_ENABLE_IN_DOMAIN
)
AZURE_SEARCH_CONTENT_COLUMNS = os.environ.get("AZURE_SEARCH_CONTENT_COLUMNS")
AZURE_SEARCH_FILENAME_COLUMN = os.environ.get("AZURE_SEARCH_FILENAME_COLUMN")
AZURE_SEARCH_TITLE_COLUMN = os.environ.get("AZURE_SEARCH_TITLE_COLUMN")
AZURE_SEARCH_URL_COLUMN = os.environ.get("AZURE_SEARCH_URL_COLUMN")
AZURE_SEARCH_VECTOR_COLUMNS = os.environ.get("AZURE_SEARCH_VECTOR_COLUMNS")
AZURE_SEARCH_QUERY_TYPE = os.environ.get("AZURE_SEARCH_QUERY_TYPE")
AZURE_SEARCH_PERMITTED_GROUPS_COLUMN = os.environ.get(
    "AZURE_SEARCH_PERMITTED_GROUPS_COLUMN"
)
AZURE_SEARCH_STRICTNESS = os.environ.get("AZURE_SEARCH_STRICTNESS", SEARCH_STRICTNESS)

# AOAI Integration Settings
AZURE_OPENAI_RESOURCE = os.environ.get("AZURE_OPENAI_RESOURCE")
AZURE_OPENAI_MODEL = os.environ.get("AZURE_OPENAI_MODEL")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_TEMPERATURE = os.environ.get("AZURE_OPENAI_TEMPERATURE", 0)
AZURE_OPENAI_TOP_P = os.environ.get("AZURE_OPENAI_TOP_P", 1.0)
AZURE_OPENAI_MAX_TOKENS = os.environ.get("AZURE_OPENAI_MAX_TOKENS", 1000)
AZURE_OPENAI_STOP_SEQUENCE = os.environ.get("AZURE_OPENAI_STOP_SEQUENCE")
AZURE_OPENAI_SYSTEM_MESSAGE = os.environ.get(
    "AZURE_OPENAI_SYSTEM_MESSAGE",
    "You are an AI assistant that helps people find information.",
)
AZURE_OPENAI_PREVIEW_API_VERSION = os.environ.get(
    "AZURE_OPENAI_PREVIEW_API_VERSION",
    MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION,
)
AZURE_OPENAI_STREAM = os.environ.get("AZURE_OPENAI_STREAM", "true")
AZURE_OPENAI_MODEL_NAME = os.environ.get(
    "AZURE_OPENAI_MODEL_NAME", "gpt-35-turbo-16k"
)  # Name of the model, e.g. 'gpt-35-turbo-16k' or 'gpt-4'
AZURE_OPENAI_EMBEDDING_ENDPOINT = os.environ.get("AZURE_OPENAI_EMBEDDING_ENDPOINT")
AZURE_OPENAI_EMBEDDING_KEY = os.environ.get("AZURE_OPENAI_EMBEDDING_KEY")
AZURE_OPENAI_EMBEDDING_NAME = os.environ.get("AZURE_OPENAI_EMBEDDING_NAME", "")

# CosmosDB Mongo vcore vector db Settings
AZURE_COSMOSDB_MONGO_VCORE_CONNECTION_STRING = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_CONNECTION_STRING"
)  # This has to be secure string
AZURE_COSMOSDB_MONGO_VCORE_DATABASE = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_DATABASE"
)
AZURE_COSMOSDB_MONGO_VCORE_CONTAINER = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_CONTAINER"
)
AZURE_COSMOSDB_MONGO_VCORE_INDEX = os.environ.get("AZURE_COSMOSDB_MONGO_VCORE_INDEX")
AZURE_COSMOSDB_MONGO_VCORE_TOP_K = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_TOP_K", AZURE_SEARCH_TOP_K
)
AZURE_COSMOSDB_MONGO_VCORE_STRICTNESS = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_STRICTNESS", AZURE_SEARCH_STRICTNESS
)
AZURE_COSMOSDB_MONGO_VCORE_ENABLE_IN_DOMAIN = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_ENABLE_IN_DOMAIN", AZURE_SEARCH_ENABLE_IN_DOMAIN
)
AZURE_COSMOSDB_MONGO_VCORE_CONTENT_COLUMNS = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_CONTENT_COLUMNS", ""
)
AZURE_COSMOSDB_MONGO_VCORE_FILENAME_COLUMN = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_FILENAME_COLUMN"
)
AZURE_COSMOSDB_MONGO_VCORE_TITLE_COLUMN = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_TITLE_COLUMN"
)
AZURE_COSMOSDB_MONGO_VCORE_URL_COLUMN = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_URL_COLUMN"
)
AZURE_COSMOSDB_MONGO_VCORE_VECTOR_COLUMNS = os.environ.get(
    "AZURE_COSMOSDB_MONGO_VCORE_VECTOR_COLUMNS"
)

SHOULD_STREAM = True if AZURE_OPENAI_STREAM.lower() == "true" else False

# Chat History CosmosDB Integration Settings
AZURE_COSMOSDB_DATABASE = os.environ.get("AZURE_COSMOSDB_DATABASE")
AZURE_COSMOSDB_ACCOUNT = os.environ.get("AZURE_COSMOSDB_ACCOUNT")
AZURE_COSMOSDB_CONVERSATIONS_CONTAINER = os.environ.get(
    "AZURE_COSMOSDB_CONVERSATIONS_CONTAINER"
)
AZURE_COSMOSDB_ACCOUNT_KEY = os.environ.get("AZURE_COSMOSDB_ACCOUNT_KEY")
AZURE_COSMOSDB_ENABLE_FEEDBACK = (
    os.environ.get("AZURE_COSMOSDB_ENABLE_FEEDBACK", "false").lower() == "true"
)

# Elasticsearch Integration Settings
ELASTICSEARCH_ENDPOINT = os.environ.get("ELASTICSEARCH_ENDPOINT")
ELASTICSEARCH_ENCODED_API_KEY = os.environ.get("ELASTICSEARCH_ENCODED_API_KEY")
ELASTICSEARCH_INDEX = os.environ.get("ELASTICSEARCH_INDEX")
ELASTICSEARCH_QUERY_TYPE = os.environ.get("ELASTICSEARCH_QUERY_TYPE", "simple")
ELASTICSEARCH_TOP_K = os.environ.get("ELASTICSEARCH_TOP_K", SEARCH_TOP_K)
ELASTICSEARCH_ENABLE_IN_DOMAIN = os.environ.get(
    "ELASTICSEARCH_ENABLE_IN_DOMAIN", SEARCH_ENABLE_IN_DOMAIN
)
ELASTICSEARCH_CONTENT_COLUMNS = os.environ.get("ELASTICSEARCH_CONTENT_COLUMNS")
ELASTICSEARCH_FILENAME_COLUMN = os.environ.get("ELASTICSEARCH_FILENAME_COLUMN")
ELASTICSEARCH_TITLE_COLUMN = os.environ.get("ELASTICSEARCH_TITLE_COLUMN")
ELASTICSEARCH_URL_COLUMN = os.environ.get("ELASTICSEARCH_URL_COLUMN")
ELASTICSEARCH_VECTOR_COLUMNS = os.environ.get("ELASTICSEARCH_VECTOR_COLUMNS")
ELASTICSEARCH_STRICTNESS = os.environ.get("ELASTICSEARCH_STRICTNESS", SEARCH_STRICTNESS)
ELASTICSEARCH_EMBEDDING_MODEL_ID = os.environ.get("ELASTICSEARCH_EMBEDDING_MODEL_ID")

# Pinecone Integration Settings
PINECONE_ENVIRONMENT = os.environ.get("PINECONE_ENVIRONMENT")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")
PINECONE_TOP_K = os.environ.get("PINECONE_TOP_K", SEARCH_TOP_K)
PINECONE_STRICTNESS = os.environ.get("PINECONE_STRICTNESS", SEARCH_STRICTNESS)
PINECONE_ENABLE_IN_DOMAIN = os.environ.get(
    "PINECONE_ENABLE_IN_DOMAIN", SEARCH_ENABLE_IN_DOMAIN
)
PINECONE_CONTENT_COLUMNS = os.environ.get("PINECONE_CONTENT_COLUMNS", "")
PINECONE_FILENAME_COLUMN = os.environ.get("PINECONE_FILENAME_COLUMN")
PINECONE_TITLE_COLUMN = os.environ.get("PINECONE_TITLE_COLUMN")
PINECONE_URL_COLUMN = os.environ.get("PINECONE_URL_COLUMN")
PINECONE_VECTOR_COLUMNS = os.environ.get("PINECONE_VECTOR_COLUMNS")

# Azure AI MLIndex Integration Settings - for use with MLIndex data assets created in Azure AI Studio
AZURE_MLINDEX_NAME = os.environ.get("AZURE_MLINDEX_NAME")
AZURE_MLINDEX_VERSION = os.environ.get("AZURE_MLINDEX_VERSION")
AZURE_ML_PROJECT_RESOURCE_ID = os.environ.get(
    "AZURE_ML_PROJECT_RESOURCE_ID"
)  # /subscriptions/{sub ID}/resourceGroups/{rg name}/providers/Microsoft.MachineLearningServices/workspaces/{AML project name}
AZURE_MLINDEX_TOP_K = os.environ.get("AZURE_MLINDEX_TOP_K", SEARCH_TOP_K)
AZURE_MLINDEX_STRICTNESS = os.environ.get("AZURE_MLINDEX_STRICTNESS", SEARCH_STRICTNESS)
AZURE_MLINDEX_ENABLE_IN_DOMAIN = os.environ.get(
    "AZURE_MLINDEX_ENABLE_IN_DOMAIN", SEARCH_ENABLE_IN_DOMAIN
)
AZURE_MLINDEX_CONTENT_COLUMNS = os.environ.get("AZURE_MLINDEX_CONTENT_COLUMNS", "")
AZURE_MLINDEX_FILENAME_COLUMN = os.environ.get("AZURE_MLINDEX_FILENAME_COLUMN")
AZURE_MLINDEX_TITLE_COLUMN = os.environ.get("AZURE_MLINDEX_TITLE_COLUMN")
AZURE_MLINDEX_URL_COLUMN = os.environ.get("AZURE_MLINDEX_URL_COLUMN")
AZURE_MLINDEX_VECTOR_COLUMNS = os.environ.get("AZURE_MLINDEX_VECTOR_COLUMNS")
AZURE_MLINDEX_QUERY_TYPE = os.environ.get("AZURE_MLINDEX_QUERY_TYPE")
# Promptflow Integration Settings
USE_PROMPTFLOW = os.environ.get("USE_PROMPTFLOW", "false").lower() == "true"
PROMPTFLOW_ENDPOINT = os.environ.get("PROMPTFLOW_ENDPOINT")
PROMPTFLOW_API_KEY = os.environ.get("PROMPTFLOW_API_KEY")
PROMPTFLOW_RESPONSE_TIMEOUT = os.environ.get("PROMPTFLOW_RESPONSE_TIMEOUT", 30.0)
# default request and response field names are input -> 'query' and output -> 'reply'
PROMPTFLOW_REQUEST_FIELD_NAME = os.environ.get("PROMPTFLOW_REQUEST_FIELD_NAME", "query")
PROMPTFLOW_RESPONSE_FIELD_NAME = os.environ.get(
    "PROMPTFLOW_RESPONSE_FIELD_NAME", "reply"
)
# Frontend Settings via Environment Variables
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "true").lower() == "true"
CHAT_HISTORY_ENABLED = (
    AZURE_COSMOSDB_ACCOUNT
    and AZURE_COSMOSDB_DATABASE
    and AZURE_COSMOSDB_CONVERSATIONS_CONTAINER
)
SANITIZE_ANSWER = os.environ.get("SANITIZE_ANSWER", "false").lower() == "true"
frontend_settings = {
    "auth_enabled": AUTH_ENABLED,
    "feedback_enabled": AZURE_COSMOSDB_ENABLE_FEEDBACK and CHAT_HISTORY_ENABLED,
    "ui": {
        "title": UI_TITLE,
        "logo": UI_LOGO,
        "chat_logo": UI_CHAT_LOGO or UI_LOGO,
        "chat_title": UI_CHAT_TITLE,
        "chat_description": UI_CHAT_DESCRIPTION,
        "show_share_button": UI_SHOW_SHARE_BUTTON,
    },
    "sanitize_answer": SANITIZE_ANSWER,
}


def should_use_data():
    global DATASOURCE_TYPE
    if AZURE_SEARCH_SERVICE and AZURE_SEARCH_INDEX:
        DATASOURCE_TYPE = "AzureCognitiveSearch"
        logging.debug("Using Azure Cognitive Search")
        return True

    if (
        AZURE_COSMOSDB_MONGO_VCORE_DATABASE
        and AZURE_COSMOSDB_MONGO_VCORE_CONTAINER
        and AZURE_COSMOSDB_MONGO_VCORE_INDEX
        and AZURE_COSMOSDB_MONGO_VCORE_CONNECTION_STRING
    ):
        DATASOURCE_TYPE = "AzureCosmosDB"
        logging.debug("Using Azure CosmosDB Mongo vcore")
        return True

    if ELASTICSEARCH_ENDPOINT and ELASTICSEARCH_ENCODED_API_KEY and ELASTICSEARCH_INDEX:
        DATASOURCE_TYPE = "Elasticsearch"
        logging.debug("Using Elasticsearch")
        return True

    if PINECONE_ENVIRONMENT and PINECONE_API_KEY and PINECONE_INDEX_NAME:
        DATASOURCE_TYPE = "Pinecone"
        logging.debug("Using Pinecone")
        return True

    if AZURE_MLINDEX_NAME and AZURE_MLINDEX_VERSION and AZURE_ML_PROJECT_RESOURCE_ID:
        DATASOURCE_TYPE = "AzureMLIndex"
        logging.debug("Using Azure ML Index")
        return True

    return False


SHOULD_USE_DATA = should_use_data()


# Initialize Azure OpenAI Client
def init_openai_client(use_data=SHOULD_USE_DATA):
    azure_openai_client = None
    try:
        # API version check
        if (
            AZURE_OPENAI_PREVIEW_API_VERSION
            < MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION
        ):
            raise Exception(
                f"The minimum supported Azure OpenAI preview API version is '{MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION}'"
            )

        # Endpoint
        if not AZURE_OPENAI_ENDPOINT and not AZURE_OPENAI_RESOURCE:
            raise Exception(
                "AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_RESOURCE is required"
            )

        endpoint = (
            AZURE_OPENAI_ENDPOINT
            if AZURE_OPENAI_ENDPOINT
            else f"https://{AZURE_OPENAI_RESOURCE}.openai.azure.com/"
        )

        # Authentication
        aoai_api_key = AZURE_OPENAI_KEY
        ad_token_provider = None
        if not aoai_api_key:
            logging.debug("No AZURE_OPENAI_KEY found, using Azure AD auth")
            ad_token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )

        # Deployment
        deployment = AZURE_OPENAI_MODEL
        if not deployment:
            raise Exception("AZURE_OPENAI_MODEL is required")

        # Default Headers
        default_headers = {"x-ms-useragent": USER_AGENT}

        azure_openai_client = AsyncAzureOpenAI(
            api_version=AZURE_OPENAI_PREVIEW_API_VERSION,
            api_key=aoai_api_key,
            azure_ad_token_provider=ad_token_provider,
            default_headers=default_headers,
            azure_endpoint=endpoint,
        )

        return azure_openai_client
    except Exception as e:
        logging.exception("Exception in Azure OpenAI initialization", e)
        azure_openai_client = None
        raise e


def init_cosmosdb_client():
    cosmos_conversation_client = None
    if CHAT_HISTORY_ENABLED:
        try:
            cosmos_endpoint = (
                f"https://{AZURE_COSMOSDB_ACCOUNT}.documents.azure.com:443/"
            )

            if not AZURE_COSMOSDB_ACCOUNT_KEY:
                credential = DefaultAzureCredential()
            else:
                credential = AZURE_COSMOSDB_ACCOUNT_KEY

            cosmos_conversation_client = CosmosConversationClient(
                cosmosdb_endpoint=cosmos_endpoint,
                credential=credential,
                database_name=AZURE_COSMOSDB_DATABASE,
                container_name=AZURE_COSMOSDB_CONVERSATIONS_CONTAINER,
                enable_message_feedback=AZURE_COSMOSDB_ENABLE_FEEDBACK,
            )
        except Exception as e:
            logging.exception("Exception in CosmosDB initialization", e)
            cosmos_conversation_client = None
            raise e
    else:
        logging.debug("CosmosDB not configured")

    return cosmos_conversation_client


def get_configured_data_source(filter):
    data_source = {}
    query_type = "simple"
    if DATASOURCE_TYPE == "AzureCognitiveSearch":
        # Set query type
        if AZURE_SEARCH_QUERY_TYPE:
            query_type = AZURE_SEARCH_QUERY_TYPE
        elif (
            AZURE_SEARCH_USE_SEMANTIC_SEARCH.lower() == "true"
            and AZURE_SEARCH_SEMANTIC_SEARCH_CONFIG
        ):
            query_type = "semantic"

        # Set authentication
        authentication = {}
        if AZURE_SEARCH_KEY:
            authentication = {"type": "api_key", "api_key": AZURE_SEARCH_KEY}
        else:
            # If key is not provided, assume AOAI resource identity has been granted access to the search service
            authentication = {"type": "system_assigned_managed_identity"}

        data_source = {
            "type": "azure_search",
            "parameters": {
                "endpoint": f"https://{AZURE_SEARCH_SERVICE}.search.windows.net",
                "authentication": authentication,
                "index_name": AZURE_SEARCH_INDEX,
                "fields_mapping": {
                    "content_fields": (
                        parse_multi_columns(AZURE_SEARCH_CONTENT_COLUMNS)
                        if AZURE_SEARCH_CONTENT_COLUMNS
                        else []
                    ),
                    "title_field": (
                        AZURE_SEARCH_TITLE_COLUMN if AZURE_SEARCH_TITLE_COLUMN else None
                    ),
                    "url_field": (
                        AZURE_SEARCH_URL_COLUMN if AZURE_SEARCH_URL_COLUMN else None
                    ),
                    "filepath_field": (
                        AZURE_SEARCH_FILENAME_COLUMN
                        if AZURE_SEARCH_FILENAME_COLUMN
                        else None
                    ),
                    "vector_fields": (
                        parse_multi_columns(AZURE_SEARCH_VECTOR_COLUMNS)
                        if AZURE_SEARCH_VECTOR_COLUMNS
                        else []
                    )
                },
                "in_scope": (
                    True if AZURE_SEARCH_ENABLE_IN_DOMAIN.lower() == "true" else False
                ),
                "top_n_documents": (
                    int(AZURE_SEARCH_TOP_K) if AZURE_SEARCH_TOP_K else int(SEARCH_TOP_K)
                ),
                "query_type": query_type,
                "semantic_configuration": (
                    AZURE_SEARCH_SEMANTIC_SEARCH_CONFIG
                    if AZURE_SEARCH_SEMANTIC_SEARCH_CONFIG
                    else ""
                ),
                "role_information": AZURE_OPENAI_SYSTEM_MESSAGE,
                "filter":filter,
                "strictness": (
                    int(AZURE_SEARCH_STRICTNESS)
                    if AZURE_SEARCH_STRICTNESS
                    else int(SEARCH_STRICTNESS)
                ),
            },
        }
    elif DATASOURCE_TYPE == "AzureCosmosDB":
        query_type = "vector"

        data_source = {
            "type": "azure_cosmos_db",
            "parameters": {
                "authentication": {
                    "type": "connection_string",
                    "connection_string": AZURE_COSMOSDB_MONGO_VCORE_CONNECTION_STRING,
                },
                "index_name": AZURE_COSMOSDB_MONGO_VCORE_INDEX,
                "database_name": AZURE_COSMOSDB_MONGO_VCORE_DATABASE,
                "container_name": AZURE_COSMOSDB_MONGO_VCORE_CONTAINER,
                "fields_mapping": {
                    "content_fields": (
                        parse_multi_columns(AZURE_COSMOSDB_MONGO_VCORE_CONTENT_COLUMNS)
                        if AZURE_COSMOSDB_MONGO_VCORE_CONTENT_COLUMNS
                        else []
                    ),
                    "title_field": (
                        AZURE_COSMOSDB_MONGO_VCORE_TITLE_COLUMN
                        if AZURE_COSMOSDB_MONGO_VCORE_TITLE_COLUMN
                        else None
                    ),
                    "url_field": (
                        AZURE_COSMOSDB_MONGO_VCORE_URL_COLUMN
                        if AZURE_COSMOSDB_MONGO_VCORE_URL_COLUMN
                        else None
                    ),
                    "filepath_field": (
                        AZURE_COSMOSDB_MONGO_VCORE_FILENAME_COLUMN
                        if AZURE_COSMOSDB_MONGO_VCORE_FILENAME_COLUMN
                        else None
                    ),
                    "vector_fields": (
                        parse_multi_columns(AZURE_COSMOSDB_MONGO_VCORE_VECTOR_COLUMNS)
                        if AZURE_COSMOSDB_MONGO_VCORE_VECTOR_COLUMNS
                        else []
                    ),
                },
                "in_scope": (
                    True
                    if AZURE_COSMOSDB_MONGO_VCORE_ENABLE_IN_DOMAIN.lower() == "true"
                    else False
                ),
                "top_n_documents": (
                    int(AZURE_COSMOSDB_MONGO_VCORE_TOP_K)
                    if AZURE_COSMOSDB_MONGO_VCORE_TOP_K
                    else int(SEARCH_TOP_K)
                ),
                "strictness": (
                    int(AZURE_COSMOSDB_MONGO_VCORE_STRICTNESS)
                    if AZURE_COSMOSDB_MONGO_VCORE_STRICTNESS
                    else int(SEARCH_STRICTNESS)
                ),
                "query_type": query_type,
                "role_information": AZURE_OPENAI_SYSTEM_MESSAGE,
            },
        }
    elif DATASOURCE_TYPE == "Elasticsearch":
        if ELASTICSEARCH_QUERY_TYPE:
            query_type = ELASTICSEARCH_QUERY_TYPE

        data_source = {
            "type": "elasticsearch",
            "parameters": {
                "endpoint": ELASTICSEARCH_ENDPOINT,
                "authentication": {
                    "type": "encoded_api_key",
                    "encoded_api_key": ELASTICSEARCH_ENCODED_API_KEY,
                },
                "index_name": ELASTICSEARCH_INDEX,
                "fields_mapping": {
                    "content_fields": (
                        parse_multi_columns(ELASTICSEARCH_CONTENT_COLUMNS)
                        if ELASTICSEARCH_CONTENT_COLUMNS
                        else []
                    ),
                    "title_field": (
                        ELASTICSEARCH_TITLE_COLUMN
                        if ELASTICSEARCH_TITLE_COLUMN
                        else None
                    ),
                    "url_field": (
                        ELASTICSEARCH_URL_COLUMN if ELASTICSEARCH_URL_COLUMN else None
                    ),
                    "filepath_field": (
                        ELASTICSEARCH_FILENAME_COLUMN
                        if ELASTICSEARCH_FILENAME_COLUMN
                        else None
                    ),
                    "vector_fields": (
                        parse_multi_columns(ELASTICSEARCH_VECTOR_COLUMNS)
                        if ELASTICSEARCH_VECTOR_COLUMNS
                        else []
                    ),
                },
                "in_scope": (
                    True if ELASTICSEARCH_ENABLE_IN_DOMAIN.lower() == "true" else False
                ),
                "top_n_documents": (
                    int(ELASTICSEARCH_TOP_K)
                    if ELASTICSEARCH_TOP_K
                    else int(SEARCH_TOP_K)
                ),
                "query_type": query_type,
                "role_information": AZURE_OPENAI_SYSTEM_MESSAGE,
                "strictness": (
                    int(ELASTICSEARCH_STRICTNESS)
                    if ELASTICSEARCH_STRICTNESS
                    else int(SEARCH_STRICTNESS)
                ),
            },
        }
    elif DATASOURCE_TYPE == "AzureMLIndex":
        if AZURE_MLINDEX_QUERY_TYPE:
            query_type = AZURE_MLINDEX_QUERY_TYPE

        data_source = {
            "type": "azure_ml_index",
            "parameters": {
                "name": AZURE_MLINDEX_NAME,
                "version": AZURE_MLINDEX_VERSION,
                "project_resource_id": AZURE_ML_PROJECT_RESOURCE_ID,
                "fieldsMapping": {
                    "content_fields": (
                        parse_multi_columns(AZURE_MLINDEX_CONTENT_COLUMNS)
                        if AZURE_MLINDEX_CONTENT_COLUMNS
                        else []
                    ),
                    "title_field": (
                        AZURE_MLINDEX_TITLE_COLUMN
                        if AZURE_MLINDEX_TITLE_COLUMN
                        else None
                    ),
                    "url_field": (
                        AZURE_MLINDEX_URL_COLUMN if AZURE_MLINDEX_URL_COLUMN else None
                    ),
                    "filepath_field": (
                        AZURE_MLINDEX_FILENAME_COLUMN
                        if AZURE_MLINDEX_FILENAME_COLUMN
                        else None
                    ),
                    "vector_fields": (
                        parse_multi_columns(AZURE_MLINDEX_VECTOR_COLUMNS)
                        if AZURE_MLINDEX_VECTOR_COLUMNS
                        else []
                    ),
                },
                "in_scope": (
                    True if AZURE_MLINDEX_ENABLE_IN_DOMAIN.lower() == "true" else False
                ),
                "top_n_documents": (
                    int(AZURE_MLINDEX_TOP_K)
                    if AZURE_MLINDEX_TOP_K
                    else int(SEARCH_TOP_K)
                ),
                "query_type": query_type,
                "role_information": AZURE_OPENAI_SYSTEM_MESSAGE,
                "strictness": (
                    int(AZURE_MLINDEX_STRICTNESS)
                    if AZURE_MLINDEX_STRICTNESS
                    else int(SEARCH_STRICTNESS)
                ),
            },
        }
    elif DATASOURCE_TYPE == "Pinecone":
        query_type = "vector"

        data_source = {
            "type": "pinecone",
            "parameters": {
                "environment": PINECONE_ENVIRONMENT,
                "authentication": {"type": "api_key", "key": PINECONE_API_KEY},
                "index_name": PINECONE_INDEX_NAME,
                "fields_mapping": {
                    "content_fields": (
                        parse_multi_columns(PINECONE_CONTENT_COLUMNS)
                        if PINECONE_CONTENT_COLUMNS
                        else []
                    ),
                    "title_field": (
                        PINECONE_TITLE_COLUMN if PINECONE_TITLE_COLUMN else None
                    ),
                    "url_field": PINECONE_URL_COLUMN if PINECONE_URL_COLUMN else None,
                    "filepath_field": (
                        PINECONE_FILENAME_COLUMN if PINECONE_FILENAME_COLUMN else None
                    ),
                    "vector_fields": (
                        parse_multi_columns(PINECONE_VECTOR_COLUMNS)
                        if PINECONE_VECTOR_COLUMNS
                        else []
                    ),
                },
                "in_scope": (
                    True if PINECONE_ENABLE_IN_DOMAIN.lower() == "true" else False
                ),
                "top_n_documents": (
                    int(PINECONE_TOP_K) if PINECONE_TOP_K else int(SEARCH_TOP_K)
                ),
                "strictness": (
                    int(PINECONE_STRICTNESS)
                    if PINECONE_STRICTNESS
                    else int(SEARCH_STRICTNESS)
                ),
                "query_type": query_type,
                "role_information": AZURE_OPENAI_SYSTEM_MESSAGE,
            },
        }
    else:
        raise Exception(
            f"DATASOURCE_TYPE is not configured or unknown: {DATASOURCE_TYPE}"
        )

    if "vector" in query_type.lower() and DATASOURCE_TYPE != "AzureMLIndex":
        embeddingDependency = {}
        if AZURE_OPENAI_EMBEDDING_NAME:
            embeddingDependency = {
                "type": "deployment_name",
                "deployment_name": AZURE_OPENAI_EMBEDDING_NAME,
            }
        elif AZURE_OPENAI_EMBEDDING_ENDPOINT and AZURE_OPENAI_EMBEDDING_KEY:
            embeddingDependency = {
                "type": "endpoint",
                "endpoint": AZURE_OPENAI_EMBEDDING_ENDPOINT,
                "authentication": {
                    "type": "api_key",
                    "key": AZURE_OPENAI_EMBEDDING_KEY,
                },
            }
        elif DATASOURCE_TYPE == "Elasticsearch" and ELASTICSEARCH_EMBEDDING_MODEL_ID:
            embeddingDependency = {
                "type": "model_id",
                "model_id": ELASTICSEARCH_EMBEDDING_MODEL_ID,
            }
        else:
            raise Exception(
                f"Vector query type ({query_type}) is selected for data source type {DATASOURCE_TYPE} but no embedding dependency is configured"
            )
        data_source["parameters"]["embedding_dependency"] = embeddingDependency

    return data_source

def create_filter_string(filter_array, filter_name):
    if filter_array:
        string = ' or '.join(f"({filter_name} eq '{item}')" for item in filter_array)
        return f"({string})"
    return ""

def prepare_model_args(request_body):
    request_messages = request_body.get("messages", [])
    messages = []
    if not SHOULD_USE_DATA:
        messages = [{"role": "system", "content": AZURE_OPENAI_SYSTEM_MESSAGE}]

    for message in request_messages:
        if message:
            messages.append({"role": message["role"], "content": message["content"]})

    # Extract the last request message filters
    types_filter_array = request_messages[-1]["types_filter"] 
    rules_filter_array = request_messages[-1]["rules_filter"] 
    parts_filter_array = request_messages[-1]["parts_filter"] 

    # Create filter strings for each filter type
    types_filter_string = create_filter_string(types_filter_array, "type")
    rules_filter_string = create_filter_string(rules_filter_array, "rule")
    parts_filter_string = create_filter_string(parts_filter_array, "part")

    # Combine the non-empty filter strings with ' and '
    filter_conditions = [condition for condition in [types_filter_string, rules_filter_string, parts_filter_string] if condition]
    filter_string = ' and '.join(filter_conditions) if filter_conditions else ""

    model_args = {
        "messages": messages,
        "temperature": float(AZURE_OPENAI_TEMPERATURE),
        "max_tokens": int(AZURE_OPENAI_MAX_TOKENS),
        "top_p": float(AZURE_OPENAI_TOP_P),
        "stop": (
            parse_multi_columns(AZURE_OPENAI_STOP_SEQUENCE)
            if AZURE_OPENAI_STOP_SEQUENCE
            else None
        ),
        "stream": SHOULD_STREAM,
        "model": AZURE_OPENAI_MODEL,
    }

    if SHOULD_USE_DATA:
        model_args["extra_body"] = {"data_sources": [get_configured_data_source(filter_string)]}

    model_args_clean = copy.deepcopy(model_args)
    if model_args_clean.get("extra_body"):
        secret_params = [
            "key",
            "connection_string",
            "embedding_key",
            "encoded_api_key",
            "api_key",
        ]
        for secret_param in secret_params:
            if model_args_clean["extra_body"]["data_sources"][0]["parameters"].get(
                secret_param
            ):
                model_args_clean["extra_body"]["data_sources"][0]["parameters"][
                    secret_param
                ] = "*****"
        authentication = model_args_clean["extra_body"]["data_sources"][0][
            "parameters"
        ].get("authentication", {})
        for field in authentication:
            if field in secret_params:
                model_args_clean["extra_body"]["data_sources"][0]["parameters"][
                    "authentication"
                ][field] = "*****"
        embeddingDependency = model_args_clean["extra_body"]["data_sources"][0][
            "parameters"
        ].get("embedding_dependency", {})
        if "authentication" in embeddingDependency:
            for field in embeddingDependency["authentication"]:
                if field in secret_params:
                    model_args_clean["extra_body"]["data_sources"][0]["parameters"][
                        "embedding_dependency"
                    ]["authentication"][field] = "*****"

    logging.debug(f"REQUEST BODY: {json.dumps(model_args_clean, indent=4)}")

    return model_args

async def promptflow_request(request):
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {PROMPTFLOW_API_KEY}",
        }
        # Adding timeout for scenarios where response takes longer to come back
        logging.debug(f"Setting timeout to {PROMPTFLOW_RESPONSE_TIMEOUT}")
        async with httpx.AsyncClient(
            timeout=float(PROMPTFLOW_RESPONSE_TIMEOUT)
        ) as client:
            pf_formatted_obj = convert_to_pf_format(
                request, PROMPTFLOW_REQUEST_FIELD_NAME, PROMPTFLOW_RESPONSE_FIELD_NAME
            )
            # NOTE: This only support question and chat_history parameters
            # If you need to add more parameters, you need to modify the request body
            response = await client.post(
                PROMPTFLOW_ENDPOINT,
                json={
                    f"{PROMPTFLOW_REQUEST_FIELD_NAME}": pf_formatted_obj[-1]["inputs"][
                        PROMPTFLOW_REQUEST_FIELD_NAME
                    ],
                    "chat_history": pf_formatted_obj[:-1],
                },
                headers=headers,
            )
        resp = response.json()
        resp["id"] = request["messages"][-1]["id"]
        return resp
    except Exception as e:
        logging.error(f"An error occurred while making promptflow_request: {e}")


async def send_chat_request(request):
    filtered_messages = []
    messages = request.get("messages", [])
    for message in messages:
        if message.get("role") != 'tool':
            filtered_messages.append(message)
            
    request['messages'] = filtered_messages
    model_args = prepare_model_args(request)

    try:
        azure_openai_client = init_openai_client()
        raw_response = await azure_openai_client.chat.completions.with_raw_response.create(**model_args)
        response = raw_response.parse()
        apim_request_id = raw_response.headers.get("apim-request-id") 
    except Exception as e:
        logging.exception("Exception in send_chat_request")
        raise e

    return response, apim_request_id


async def complete_chat_request(request_body):
    request_messages = request_body.get("messages", [])
    if USE_PROMPTFLOW and PROMPTFLOW_ENDPOINT and PROMPTFLOW_API_KEY:
        response = await promptflow_request(request_body)
        history_metadata = request_body.get("history_metadata", {})
        return format_pf_non_streaming_response(
            response, history_metadata, PROMPTFLOW_RESPONSE_FIELD_NAME
        )
    else:
        response, apim_request_id = await send_chat_request(request_body)
        history_metadata = request_body.get("history_metadata", {})
        return format_non_streaming_response(response, history_metadata, apim_request_id)



async def stream_chat_request(request_body):
    response, apim_request_id = await send_chat_request(request_body)
    history_metadata = request_body.get("history_metadata", {})
    async def generate():
        async for completionChunk in response:
            yield format_stream_response(completionChunk, history_metadata, apim_request_id)

    return generate()


async def conversation_internal(request_body):
    try:
        if SHOULD_STREAM:
            result = await stream_chat_request(request_body)
            # result.choices[0].message.content = append_SAS_to_image_link(response.choices[0].message.content),
            response = await make_response(format_as_ndjson(result))
            response.timeout = None
            response.mimetype = "application/json-lines"
            return response
        else:
            result = await complete_chat_request(request_body)
            return jsonify(result)

    except Exception as ex:
        logging.exception(ex)
        if hasattr(ex, "status_code"):
            return jsonify({"error": str(ex)}), ex.status_code
        else:
            return jsonify({"error": str(ex)}), 500


@bp.route("/conversation", methods=["POST"])
async def conversation():
    if not request.is_json:
        return jsonify({"error": "request must be json"}), 415
    request_json = await request.get_json()

    return await conversation_internal(request_json)


@bp.route("/frontend_settings", methods=["GET"])
def get_frontend_settings():
    try:
        return jsonify(frontend_settings), 200
    except Exception as e:
        logging.exception("Exception in /frontend_settings")
        return jsonify({"error": str(e)}), 500

## Conversation History API ##
@bp.route("/history/generate", methods=["POST"])
async def add_conversation():
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        # make sure cosmos is configured
        cosmos_conversation_client = init_cosmosdb_client()
        if not cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        # check for the conversation_id, if the conversation is not set, we will create a new one
        history_metadata = {}
        if not conversation_id:
            title = await generate_title(request_json["messages"])
            conversation_dict = await cosmos_conversation_client.create_conversation(
                user_id=user_id, title=title
            )
            conversation_id = conversation_dict["id"]
            history_metadata["title"] = title
            history_metadata["date"] = conversation_dict["createdAt"]

        ## Format the incoming message object in the "chat/completions" messages format
        ## then write it to the conversation history in cosmos
        messages = request_json["messages"]
        if len(messages) > 0 and messages[-1]["role"] == "user":
            createdMessageValue = await cosmos_conversation_client.create_message(
                uuid=str(uuid.uuid4()),
                conversation_id=conversation_id,
                user_id=user_id,
                input_message=messages[-1],
            )
            if createdMessageValue == "Conversation not found":
                raise Exception(
                    "Conversation not found for the given conversation ID: "
                    + conversation_id
                    + "."
                )
        else:
            raise Exception("No user message found")

        await cosmos_conversation_client.cosmosdb_client.close()

        # Submit request to Chat Completions for response
        request_body = await request.get_json()
        history_metadata["conversation_id"] = conversation_id
        request_body["history_metadata"] = history_metadata                
        return await conversation_internal(request_body)

    except Exception as e:
        logging.exception("Exception in /history/generate")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/update", methods=["POST"])
async def update_conversation():
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        # make sure cosmos is configured
        cosmos_conversation_client = init_cosmosdb_client()
        if not cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        # check for the conversation_id, if the conversation is not set, we will create a new one
        if not conversation_id:
            raise Exception("No conversation_id found")

        ## Format the incoming message object in the "chat/completions" messages format
        ## then write it to the conversation history in cosmos
        messages = request_json["messages"]
        if len(messages) > 0 and messages[-1]["role"] == "assistant":
            if len(messages) > 1 and messages[-2].get("role", None) == "tool":
                # write the tool message first
                content = json.loads(messages[-2].get("content", None))
                for i, chunk in enumerate(content["citations"]):
                    content["citations"][i]["url"]=remove_SAS_token(chunk["url"])
                messages[-2]["content"] = json.dumps(content)
                await cosmos_conversation_client.create_message(
                    uuid=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    user_id=user_id,
                    input_message=messages[-2]
                )
            # write the assistant message
            messages[-1]['content'] = remove_SAS_from_image_link(messages[-1]['content'])
            await cosmos_conversation_client.create_message(
                uuid=messages[-1]["id"],
                conversation_id=conversation_id,
                user_id=user_id,
                input_message=messages[-1],
            )
        else:
            raise Exception("No bot messages found")

        # Submit request to Chat Completions for response
        await cosmos_conversation_client.cosmosdb_client.close()
        response = {"success": True}
        return jsonify(response), 200

    except Exception as e:
        logging.exception("Exception in /history/update")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/message_feedback", methods=["POST"])
async def update_message():
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]
    cosmos_conversation_client = init_cosmosdb_client()

    ## check request for message_id
    request_json = await request.get_json()
    message_id = request_json.get("message_id", None)
    message_feedback = request_json.get("message_feedback", None)
    try:
        if not message_id:
            return jsonify({"error": "message_id is required"}), 400

        if not message_feedback:
            return jsonify({"error": "message_feedback is required"}), 400

        ## update the message in cosmos
        updated_message = await cosmos_conversation_client.update_message_feedback(
            user_id, message_id, message_feedback
        )
        if updated_message:
            return (
                jsonify(
                    {
                        "message": f"Successfully updated message with feedback {message_feedback}",
                        "message_id": message_id,
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {
                        "error": f"Unable to update message {message_id}. It either does not exist or the user does not have access to it."
                    }
                ),
                404,
            )

    except Exception as e:
        logging.exception("Exception in /history/message_feedback")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/delete", methods=["DELETE"])
async def delete_conversation():
    ## get the user id from the request headers
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        if not conversation_id:
            return jsonify({"error": "conversation_id is required"}), 400

        ## make sure cosmos is configured
        cosmos_conversation_client = init_cosmosdb_client()
        if not cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        ## delete the conversation messages from cosmos first
        deleted_messages = await cosmos_conversation_client.delete_messages(
            conversation_id, user_id
        )

        ## Now delete the conversation
        deleted_conversation = await cosmos_conversation_client.delete_conversation(
            user_id, conversation_id
        )

        await cosmos_conversation_client.cosmosdb_client.close()

        return (
            jsonify(
                {
                    "message": "Successfully deleted conversation and messages",
                    "conversation_id": conversation_id,
                }
            ),
            200,
        )
    except Exception as e:
        logging.exception("Exception in /history/delete")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/list", methods=["GET"])
async def list_conversations():
    offset = request.args.get("offset", 0)
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## make sure cosmos is configured
    cosmos_conversation_client = init_cosmosdb_client()
    if not cosmos_conversation_client:
        raise Exception("CosmosDB is not configured or not working")

    ## get the conversations from cosmos
    conversations = await cosmos_conversation_client.get_conversations(
        user_id, offset=offset, limit=25
    )
    await cosmos_conversation_client.cosmosdb_client.close()
    if not isinstance(conversations, list):
        return jsonify({"error": f"No conversations for {user_id} were found"}), 404

    ## return the conversation ids

    return jsonify(conversations), 200


@bp.route("/history/read", methods=["POST"])
async def get_conversation():
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    if not conversation_id:
        return jsonify({"error": "conversation_id is required"}), 400

    ## make sure cosmos is configured
    cosmos_conversation_client = init_cosmosdb_client()
    if not cosmos_conversation_client:
        raise Exception("CosmosDB is not configured or not working")

    ## get the conversation object and the related messages from cosmos
    conversation = await cosmos_conversation_client.get_conversation(
        user_id, conversation_id
    )
    ## return the conversation id and the messages in the bot frontend format
    if not conversation:
        return (
            jsonify(
                {
                    "error": f"Conversation {conversation_id} was not found. It either does not exist or the logged in user does not have access to it."
                }
            ),
            404,
        )

    # get the messages for the conversation from cosmos
    conversation_messages = await cosmos_conversation_client.get_messages(
        user_id, conversation_id
    )

    ## format the messages in the bot frontend format
    messages = [
        {
            "id": msg["id"],
            "role": msg["role"],
            "content": msg["content"],
            "createdAt": msg["createdAt"],
            "feedback": msg.get("feedback"),
            'types_filter':msg.get('typeFilter', []),
            'rules_filter':msg.get('ruleFilter', []),
            'parts_filter':msg.get('partFilter', [])
        }
        for msg in conversation_messages
    ]

    await cosmos_conversation_client.cosmosdb_client.close()
    return jsonify({"conversation_id": conversation_id, "messages": messages}), 200


@bp.route("/history/rename", methods=["POST"])
async def rename_conversation():
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    if not conversation_id:
        return jsonify({"error": "conversation_id is required"}), 400

    ## make sure cosmos is configured
    cosmos_conversation_client = init_cosmosdb_client()
    if not cosmos_conversation_client:
        raise Exception("CosmosDB is not configured or not working")

    ## get the conversation from cosmos
    conversation = await cosmos_conversation_client.get_conversation(
        user_id, conversation_id
    )
    if not conversation:
        return (
            jsonify(
                {
                    "error": f"Conversation {conversation_id} was not found. It either does not exist or the logged in user does not have access to it."
                }
            ),
            404,
        )

    ## update the title
    title = request_json.get("title", None)
    if not title:
        return jsonify({"error": "title is required"}), 400
    conversation["title"] = title
    updated_conversation = await cosmos_conversation_client.upsert_conversation(
        conversation
    )

    await cosmos_conversation_client.cosmosdb_client.close()
    return jsonify(updated_conversation), 200


@bp.route("/history/delete_all", methods=["DELETE"])
async def delete_all_conversations():
    ## get the user id from the request headers
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    # get conversations for user
    try:
        ## make sure cosmos is configured
        cosmos_conversation_client = init_cosmosdb_client()
        if not cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        conversations = await cosmos_conversation_client.get_conversations(
            user_id, offset=0, limit=None
        )
        if not conversations:
            return jsonify({"error": f"No conversations for {user_id} were found"}), 404

        # delete each conversation
        for conversation in conversations:
            ## delete the conversation messages from cosmos first
            deleted_messages = await cosmos_conversation_client.delete_messages(
                conversation["id"], user_id
            )

            ## Now delete the conversation
            deleted_conversation = await cosmos_conversation_client.delete_conversation(
                user_id, conversation["id"]
            )
        await cosmos_conversation_client.cosmosdb_client.close()
        return (
            jsonify(
                {
                    "message": f"Successfully deleted conversation and messages for user {user_id}"
                }
            ),
            200,
        )

    except Exception as e:
        logging.exception("Exception in /history/delete_all")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/clear", methods=["POST"])
async def clear_messages():
    ## get the user id from the request headers
    authenticated_user = get_authenticated_user_details(request_headers=request.headers)
    user_id = authenticated_user["user_principal_id"]

    ## check request for conversation_id
    request_json = await request.get_json()
    conversation_id = request_json.get("conversation_id", None)

    try:
        if not conversation_id:
            return jsonify({"error": "conversation_id is required"}), 400

        ## make sure cosmos is configured
        cosmos_conversation_client = init_cosmosdb_client()
        if not cosmos_conversation_client:
            raise Exception("CosmosDB is not configured or not working")

        ## delete the conversation messages from cosmos
        deleted_messages = await cosmos_conversation_client.delete_messages(
            conversation_id, user_id
        )

        return (
            jsonify(
                {
                    "message": "Successfully deleted messages in conversation",
                    "conversation_id": conversation_id,
                }
            ),
            200,
        )
    except Exception as e:
        logging.exception("Exception in /history/clear_messages")
        return jsonify({"error": str(e)}), 500


@bp.route("/history/ensure", methods=["GET"])
async def ensure_cosmos():
    if not AZURE_COSMOSDB_ACCOUNT:
        return jsonify({"error": "CosmosDB is not configured"}), 404

    try:
        cosmos_conversation_client = init_cosmosdb_client()
        success, err = await cosmos_conversation_client.ensure()
        if not cosmos_conversation_client or not success:
            if err:
                return jsonify({"error": err}), 422
            return jsonify({"error": "CosmosDB is not configured or not working"}), 500

        await cosmos_conversation_client.cosmosdb_client.close()
        return jsonify({"message": "CosmosDB is configured and working"}), 200
    except Exception as e:
        logging.exception("Exception in /history/ensure")
        cosmos_exception = str(e)
        if "Invalid credentials" in cosmos_exception:
            return jsonify({"error": cosmos_exception}), 401
        elif "Invalid CosmosDB database name" in cosmos_exception:
            return (
                jsonify(
                    {
                        "error": f"{cosmos_exception} {AZURE_COSMOSDB_DATABASE} for account {AZURE_COSMOSDB_ACCOUNT}"
                    }
                ),
                422,
            )
        elif "Invalid CosmosDB container name" in cosmos_exception:
            return (
                jsonify(
                    {
                        "error": f"{cosmos_exception}: {AZURE_COSMOSDB_CONVERSATIONS_CONTAINER}"
                    }
                ),
                422,
            )
        else:
            return jsonify({"error": "CosmosDB is not working"}), 500


async def generate_title(conversation_messages):
    ## make sure the messages are sorted by _ts descending
    title_prompt = 'Summarize the conversation so far into a 4-word or less title. Do not use any quotation marks or punctuation. Respond with a json object in the format {{"title": string}}. Do not include any other commentary or description.'

    messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in conversation_messages
    ]
    messages.append({"role": "user", "content": title_prompt})

    try:
        azure_openai_client = init_openai_client(use_data=False)
        response = await azure_openai_client.chat.completions.create(
            model=AZURE_OPENAI_MODEL, messages=messages, temperature=1, max_tokens=64
        )

        title = json.loads(response.choices[0].message.content)["title"]
        return title
    except Exception as e:
        return messages[-2]["content"]

# @bp.route("/skillset/image_offsets", methods=["POST"]) 
# async def calculate_image_offset():
#     try:
#         request_json = await request.get_json()
#         values = request_json.get("values", None)
#         reponse_array = []
#         for item in values: # going through each document
#             logging.info("Getting offsets for Document URL")
#             url = item["data"]["url"]
#             response = requests.get(f"{url}?{generate_SAS(url)}")
#             if response.status_code ==200:
#                 logging.info("Document successfully fetched")
#                 doc = Document(BytesIO(response.content))
#                 root = ET.fromstring(doc._element.xml)
                
#                 logging.info("XML successfully extracted")
#                 offsets = []
#                 count_characters = 0
#                 dpi = 96
        
#                 for elem in root.iter():
#                     # Check if the element is a text element with the correct tag
#                     if elem.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t':
#                         count_characters += len(elem.text)
#                     # Check if the element is a drawing element
#                     elif elem.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing':
#                         # If we encounter a drawing tag, we save the current text block and reset the text and counter
#                         # offsets.append(count_characters)
#                         extent_elem = elem.find('.//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent')
#                         if extent_elem is not None:
#                             cy_value = int(extent_elem.get('cy', '0'))
#                             height_pixel = (cy_value / 914400)*dpi
#                             cx_value = int(extent_elem.get('cx', '0'))
#                             width_pixel = (cx_value / 914400)*dpi
#                             if height_pixel > 35 and width_pixel > 35:
#                                 logging.info("Including Image")
#                                 offsets.append(count_characters)
 
#                 logging.info(f"{len(offsets)} images found.")

#             output={
#                 "recordId": item['recordId'],
#                 "data": {
#                     "image_offsets": offsets
#                 },
#                 "errors": None,
#                 "warnings": None
#             }
#             reponse_array.append(output)
#         response = jsonify({"values":reponse_array})
#         return response, 200  # Status code should be 200 for success
#     except Exception as e:
#         logging.exception("Exception in /skillset/image_offsets")
#         exception = str(e)
#         return jsonify({"error": exception}), 500

# @bp.route("/skillset/image_urls", methods=["POST"]) 
# async def creating_insert_text():
#     try:
#         request_json = await request.get_json()
#         values = request_json.get("values", None)
#         reponse_array = []
#         for item in values: # going through each document
#             logging.info(f"Getting urls for Document {item['recordId']}")
#             urls = item["data"]["urls"]
#             insert_text = [f"![]({url})" for url in urls]   

#             output={
#                 "recordId": item['recordId'],
#                 "data": {
#                     "image_urls": insert_text
#                 },
#                 "errors": None,
#                 "warnings": None
#             }
#             reponse_array.append(output)
#             logging.info(f"{len(urls)} Image Urls extracted")
#         response = jsonify({"values":reponse_array})
#         return response, 200  # Status code should be 200 for success
#     except Exception as e:
#         logging.exception("Exception in /skillset/image_urls")
#         exception = str(e)
#         return jsonify({"error": exception}), 500

def calculate_page_number(midpoint_offset, page_list):
    for page in page_list:
        if page["Start"] <= midpoint_offset <= page["End"]:
            return page["Page"]
    return None  # Return None if no page matches

@bp.route("/skillset/page", methods=["POST"]) 
async def get_page_number():
    try:
        request_json = await request.get_json()
        values = request_json.get("values", None)
        array = []
        for item in values:
            offsets = item["data"]["offsets"] # offsets from the Merge Skill
            pages = item["data"]["pages"] # chunks from the Split Skill
            page_list = []
            previous_offset = 0
            index = 0
            for offset in offsets:
                index += 1
                midpoint = (previous_offset + offset) // 2  # Calculate the midpoint
                page_list.append({"Page": index, "Start": previous_offset + 1, "End": offset, "Midpoint": midpoint})
                previous_offset = offset

            chunks = []
            total_offset = 0
            for i, text in enumerate(pages):
                if i == 0:
                    midpoint_offset = total_offset + (len(text)) // 2  # Calculate the midpoint for the current page
                    total_offset += len(text)
                else:
                    midpoint_offset = total_offset + (len(text) - 500) // 2  # Calculate the midpoint for the current page
                    total_offset += len(text) - 500
                chunks.append({"text":text, "page_number":calculate_page_number(midpoint_offset, page_list)})  # Use the midpoint to get the page number

            output={
                "recordId": item['recordId'],
                "data": {
                    "chunks": chunks
                },
                "errors": None,
                "warnings": None
            }
            array.append(output)
        response = jsonify({"values":array})
        return response, 200  # Status code should be 200 for success

    except Exception as e:
        logging.exception("Exception in /skillset/page")
        exception = str(e)
        return jsonify({"error": exception}), 500
    
class FormulaProcessingError(Exception):
    pass

def screenshot_formula(image_bytes, formula_filepath, points):
    try:
        blob_service_client = BlobServiceClient(BLOB_ACCOUNT, credential=BLOB_CREDENTIAL)
        image = Image.open(BytesIO(image_bytes))
        x1, y1 = points[0].x, points[0].y
        x2, y2 = points[2].x, points[2].y
        x1 -= 10
        x2 += 10
        y2 += 10
        cropped_image = image.crop((x1, y1, x2, y2)) 
        image_stream = BytesIO()
        cropped_image.save(image_stream, format='JPEG') 
        image_stream.seek(0) 
        logging.info("Saving image to blob storage")
        content_settings = ContentSettings(content_type="image/jpeg")
        blob_client = blob_service_client.get_blob_client(container=FORMULA_IMAGE_CONTAINER, blob=formula_filepath)
        blob_client.upload_blob(image_stream.getvalue(), content_settings=content_settings, blob_type="BlockBlob", overwrite=True)
        logging.info("Successfully saved image to blob storage")
    except Exception as e:
        logging.exception("Failed to process and upload screenshot")
        raise FormulaProcessingError(f"Error processing screenshot for {formula_filepath}") from e

class PolygonProcessingError(Exception):
    pass

def get_top_left(polygon):
    try:
        min_x = min(point.x for point in polygon)
        min_y = min(point.y for point in polygon)
        return min_x, min_y
    except Exception as e:
        raise PolygonProcessingError(f"Failed to get top left point of the polygon: {e}")

def compare_reading_order(polygon1, polygon2):
    try:
        point1_x, point1_y = get_top_left(polygon1)
        point2_x, point2_y = get_top_left(polygon2)
        if point1_y < point2_y:
            return True
        elif point1_y == point2_y and point1_x < point2_x:
            return True
        else:
            return False
    except PolygonProcessingError as e:
        raise e
    except Exception as e:
        raise PolygonProcessingError(f"Failed to compare reading order of polygons: {e}")

def insert_in_reading_order(array, formula):
    try:
        new_polygon = formula['polygon']
        insert_index = 0
        for i, item in enumerate(array):
            if compare_reading_order(item['polygon'], new_polygon):
                insert_index = i + 1
        array.insert(insert_index, formula)
        return array
    except PolygonProcessingError as e:
        raise e
    except Exception as e:
        raise PolygonProcessingError(f"Failed to insert formula in reading order: {e}")


Point=namedtuple('Point',['x','y'])

def get_x_length(polygon):
    x_coords = [point[0] for point in polygon]
    min_x = min(x_coords)
    max_x = max(x_coords)
    length = max_x - min_x
    return length
 
def get_vertical_distance(top, bottom):
    y_coords_top = [point[1] for point in top]
    y_coords_bottom = [point[1] for point in bottom]
    top_y = max(y_coords_top)
    bottom_y = min(y_coords_bottom)
    distance = bottom_y - top_y
    return distance
 
def get_combined_polygon(polygons):
    x_coords = [point.x for poly in polygons for point in poly]
    y_coords = [point.y for poly in polygons for point in poly]
    top_left = Point(min(x_coords), min(y_coords))
    top_right = Point(max(x_coords), min(y_coords))
    bottom_right = Point(max(x_coords), max(y_coords))
    bottom_left = Point(min(x_coords), max(y_coords))
    return [top_left, top_right, bottom_right, bottom_left]

def generate_filename(url, id):    
    pattern = fr'{BLOB_ACCOUNT}/([\w-]+)/([\w-]+)/binary/([\w-]+)\.jpg'
    match = re.search(pattern, url)
    file_source = match.group(2) if match.group(2) else str(uuid.uuid4())
    page_source = match.group(3) if match.group(2) else str(uuid.uuid4())
    return f"formula_{file_source}_{page_source}_{id}.jpg"

def get_relevant_formula(url, result, width):
    if not result.pages[0].formulas:
        return []
    return [
        {
            "polygon":f.polygon, 
            "content":generate_filename(url, formula_id), 
            "type":"formula"
        } 
        for formula_id, f in enumerate(result.pages[0].formulas) 
        # Filter formulas that have a significant width
        if get_x_length(f.polygon) > width
    ]

@bp.route("/skillset/formula", methods=["POST"])
async def get_formula():
    try:
        request_json = await request.get_json()
        if not request_json or "values" not in request_json:
            raise ValueError("Invalid request payload")
        values = request_json.get("values", None)
        response_array = []
        document_analysis_client = DocumentAnalysisClient(
            endpoint=DOCUMENT_INTELLIGENCE_ENDPOINT, credential=AzureKeyCredential(DOCUMENT_INTELLIGENCE_KEY)
        )
        errors = None
        warnings = None
        document_blob_container, blob_name = split_url(values[0]["data"]["image"]["url"])
        logging.info(f"{len(values)} pages received for Document {document_blob_container}")
        for page_number, item in enumerate(values): # going through the pages
            url = item["data"]["image"]["url"]
            image_data = item["data"]["image"]["data"]
            logging.info(f"Starting Page {page_number} ({url})")
            image_bytes = base64.b64decode(image_data)
            formulas_output =[]
            offsets=[]
            total_page_characters = 0
            logging.info(f"Page {page_number} ({url}) start analyzing.")
            # result = analyze_document_with_retries(document_analysis_client, url_with_sas)
            poller = document_analysis_client.begin_analyze_document(
                "prebuilt-read", document=image_bytes, features=[AnalysisFeature.FORMULAS]
            )
            result = poller.result()
            logging.info(f"Page {page_number} ({url}) successfully analyzed.")
            if len(result.pages[0].words)>0:
                content = [{"polygon": obj.polygon, "content": obj.content, "type": "text"} for obj in result.pages[0].words]
                formulas = get_relevant_formula(url, result, 50)
                combined_formulas = []
                polygons = []
                for i, formula in enumerate(formulas):
                    current_poly = formula["polygon"]
                    polygons.append(current_poly)
                    # Check if we should combine polygons or if we are at the last formula
                    is_last_formula = i == len(formulas) - 1
                    is_far_enough = is_last_formula or get_vertical_distance(current_poly, formulas[i + 1]["polygon"]) >= 20

                    if is_far_enough:
                        combined_polygon = get_combined_polygon(polygons)
                        formula["polygon"] = combined_polygon
                        combined_formulas.append(formula)
                        logging.info(f"Saving screenshot from Page {index} ({url})")
                        screenshot_formula(image_bytes, formula["content"], combined_polygon)
                        logging.info(f"Successfully saved screenshot from Page {index} ({url})")
                        polygons = []  # Reset polygons for the next group
                # Insert formulas into the reading order
                logging.info("Inserting formulas into reading order")
                for formula in combined_formulas:
                    content = insert_in_reading_order(content, formula)
                logging.info("Successfully inserted formulas into reading order")

                # Update offsets and output
                for obj in content:
                    if obj["type"]=="formula":
                        logging.info("Appending character offsets and url")
                        offsets.append(total_page_characters)
                        formulas_output.append(f'![]({BLOB_ACCOUNT}/{FORMULA_IMAGE_CONTAINER}/{obj["content"]})')
                        logging.info("Successfully appended character offsets and url")
                    else:
                        total_page_characters += (len(obj["content"])+1)
        
            output={
                "recordId": item['recordId'],
                "data": {
                    "formula": formulas_output,
                    "offset": offsets
                },
                "errors": errors,
                "warnings": warnings
            }
            response_array.append(output)
            logging.info(f"Completed Page {page_number} ({url})")
        response = jsonify({"values":response_array})
        logging.info("Completed request for Document {document_blob_container}")
        return response, 200  # Status code should be 200 for success
    except HttpResponseError as hre:
        logging.exception("HttpResponseError in /skillset/formula")
        return jsonify({"HttpResponseError error": str(hre)}), 500
    except FormulaProcessingError as fpe:
        logging.exception("Formula processing error in /skillset/formula")
        return jsonify({"Formula error": str(fpe)}), 500
    except ValueError as ve:
        logging.exception("Value error in /skillset/formula")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logging.exception("Unexpected exception in /skillset/formula")
        return jsonify({"Unexpected error": str(e)}), 500
 
def get_images_from_file(blob_service_client, url):
    word_container, blob = split_url(url)
    temp_doc_path = f'{LOCAL_TEMP_DIR}{blob}'
    download_file(blob_service_client, url)
    text_with_subscript = extract_text_with_subscript(temp_doc_path)
    pdf_name = docx_to_pdf_name(temp_doc_path)
    pdf_url = f"{BLOB_ACCOUNT}/{PDF_CONTAINER}/{pdf_name}"
    local_pdf_filename = download_file(blob_service_client, pdf_url)
    pdf_path = f'{LOCAL_TEMP_DIR}{local_pdf_filename}'
    file_name = local_pdf_filename.replace(".pdf","")
    # Convert PDF to a list of images
    images = convert_from_path(pdf_path)
    images_array = []
    # Upload each image to Blob Storage
    for i, image in enumerate(images):
        # Convert image to bytes
        img_byte_arr = BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()
        # Create a new blob for the image
        image_blob_name = f"{file_name}_page_{i+1}.png"
        upload_images_to_blob_storage(blob_service_client, img_byte_arr, image_blob_name)
        images_array.append(f"{BLOB_ACCOUNT}/{PAGE_IMAGE_CONTAINER}/{image_blob_name}")
    print("Finished image upload.")
    os.remove(pdf_path)
    print("Removed PDF from local machine.")
    os.remove(temp_doc_path)
    print("Removed docx from local machine.")
    return images_array, text_with_subscript, pdf_url

    # original_container, blob = split_url(url)
    # temp_doc_path = f'{LOCAL_TEMP_DIR}{blob}'
    # text_with_subscript=""
    # if ".docx" in blob:
    #     download_file(blob_service_client, url)
    #     text_with_subscript = extract_text_with_subscript(temp_doc_path)
    # images, blob_name = convert_docx_to_images(blob_service_client, temp_doc_path, LOCAL_TEMP_DIR)
    # os.remove(temp_doc_path)
    # print("Removed docx from local machine.")
    # return images, text_with_subscript, f'{BLOB_ACCOUNT}/{PDF_CONTAINER}/{blob_name}'

@bp.route("/skillset/page_images", methods=["POST"])
async def get_page_images():
    try:
        request_json = await request.get_json()
        if not request_json or "values" not in request_json:
            raise ValueError("Invalid request payload")
        values = request_json.get("values", None)
        blob_service_client = BlobServiceClient(BLOB_ACCOUNT, credential=BLOB_CREDENTIAL)
        response_array = []
        for item in values:
            url = item["data"]["url"]
            images, docx_text, pdf = get_images_from_file(blob_service_client, url)

            output={
                "recordId": item['recordId'],
                "data": {
                    "images": images,
                    "docx_text": docx_text,
                    "pdf_url":pdf
                },
                "errors": None,
                "warnings": None
            }
            response_array.append(output)
        response = jsonify({"values":response_array})
        return response, 200  # Status code should be 200 for success
    except Exception as e:
        logging.exception("Unexpected exception in /skillset/page_images")
        return jsonify({"Unexpected error": str(e)}), 500

def get_cleaned_up_text(blob_service_client, document_analysis_client, image_url, docx_text):
    blob_container, blob_name = split_url(image_url)
    image_blob_client = blob_service_client.get_blob_client(container = blob_container, blob =blob_name)
    downloader = image_blob_client.download_blob()
    image_bytes = downloader.readall()
    poller = document_analysis_client.begin_analyze_document(
        "prebuilt-read", document=image_bytes, features=[AnalysisFeature.FORMULAS]
    )
    result = poller.result()
 
    if len(result.pages[0].words)>0:
        content = result.pages[0].words
        formulas = get_relevant_formula(image_url, result)
        for i, formula in enumerate(formulas):
            screenshot_formula(blob_service_client, image_bytes, formula.content, formula.polygon)
            formula.content=f'![]({BLOB_ACCOUNT}/{FORMULA_IMAGE_CONTAINER}/{formula.content}'
 
        updated_content = overwrite_words_with_formulas(content, formulas)
 
    ocr_text = " ".join(item.content for item in updated_content)
    final_text = clean_ocr_text(docx_text, ocr_text)
    return final_text

@bp.route("/skillset/clean_text", methods=["POST"])
async def extract_page_images():
    try:
        request_json = await request.get_json()
        if not request_json or "values" not in request_json:
            raise ValueError("Invalid request payload")
        values = request_json.get("values", None)
        blob_service_client = BlobServiceClient(BLOB_ACCOUNT, credential=BLOB_CREDENTIAL)
        document_analysis_client = DocumentAnalysisClient(
            endpoint=DOCUMENT_INTELLIGENCE_ENDPOINT,
            credential=AzureKeyCredential(DOCUMENT_INTELLIGENCE_KEY)
        )
        response_array = []
        for item in values:
            image_url = item["data"]["url"]
            docx_text = item["data"]["docx_text"]
            final_text = get_cleaned_up_text(blob_service_client, document_analysis_client, image_url, docx_text)

            output={
                "recordId": item['recordId'],
                "data": {
                    "text": final_text
                },
                "errors": None,
                "warnings": None
            }
            response_array.append(output)
        response = jsonify({"values":response_array})
        return response, 200  # Status code should be 200 for success
    except Exception as e:
        logging.exception("Unexpected exception in /skillset/clean_text")
        return jsonify({"Unexpected error": str(e)}), 500

app = create_app()
