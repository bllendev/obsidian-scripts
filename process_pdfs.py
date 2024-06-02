import os
import subprocess
import fitz  # PyMuPDF
import openai
from pdf2image import convert_from_path
from PIL import Image
import io
import base64
import requests
import shutil
import json
from datetime import datetime, timedelta
import logging


# Set up logging to print to the console and to a file
LOG_FILE_PATH = '/app/logs/process_pdfs.log'
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(LOG_FILE_PATH),
    logging.StreamHandler()
])

# Define your paths
GOOGLE_DRIVE_PATH = '/app/pdfs'
OBSIDIAN_BASE_PATH = '/app/obsidian'
OBSIDIAN_STATIC_PATH = os.path.join(OBSIDIAN_BASE_PATH, 'knowledge', 'static')
ROBOCOPY_LOG = '/app/logs/robocopy_log.txt'
SYNC_SUMMARY_LOG = '/app/logs/sync_summary_log.txt'
JSON_LOG_PATH = '/app/logs/pdf_processing_log.json'


### GPT instructions
api_instructions = f"""
Work as the worlds best OCR tool. Diagram or extract the information as notes in clear markdown formatting.
If a diagram is present, recreate it in sensible markdown formatting (including the use of tables).
If in a language other than english, add a translation at the bottom of the note.
"""

# call with api_second_instructions.format(context=context)
api_second_instructions = """
If there is instructions in the image of notes as to what you should do to format (you would be
referenced as GPT) than follow said instructions, using the follow context as well..{context}.
"""

# Define the dictionary for YAML mappings
yaml_mappings = {
    'korean': {'tag': ['learn', 'sync'], 'type': 'korean'},
    'kalibre': {'tag': ['kalibre', 'sync']},
    'reporty': {'tag': ['reporty', 'sync']},
    'personal': {'tag': ['personal', 'sync']},
    'dreams': {'tag': ['personal', 'sync'], 'type': 'dreams'},
    # Add more mappings as needed
}

# Set up OpenAI API key from environment variable
openai.api_key = os.getenv('OPENAI_API_KEY')

def encode_image(image):
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{img_str}"

def ocr_and_extract_text(pdf_path):
    # Convert PDF pages to images
    images = convert_from_path(pdf_path)
    text = ""
    for image in images:
        base64_image = encode_image(image)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai.api_key}"
        }

        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": api_instructions,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": base64_image
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1000
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response_json = response.json()

        try:
            text += response_json['choices'][0]['message']['content']
        except KeyError as e:
            logging.info(f'{response_json}')
            raise e
        
        # Check if there are any instructions to follow
        if "GPT" in text:
            context = text
            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": api_second_instructions.format(context=context),
                            },
                        ]
                    }
                ],
                "max_tokens": 1000
            }
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response_json = response.json()
            text += response_json['choices'][0]['message']['content']

    logging.info(f"Extracted text: {text}")
    return text

def get_yaml_properties(title):
    properties = {"tag": []}
    for key, value in yaml_mappings.items():
        if key.lower() in title.lower():
            for k, v in value.items():
                if k == 'tag':
                    if isinstance(v, list):
                        properties['tag'].extend(v)
                    else:
                        properties['tag'].append(v)
                else:
                    properties[k] = v
    # Remove duplicate tags
    properties['tag'] = list(set(properties['tag']))
    return properties

def create_markdown_note_in_obsidian(pdf_path, text, markdown_path, static_pdf_path):
    logging.info(f"Creating Markdown note for {pdf_path}")
    # Delete the existing PDF file if it exists and then move the new one
    os.makedirs(os.path.dirname(static_pdf_path), exist_ok=True)
    try:
        # if os.path.exists(static_pdf_path):
        #     logging.info(f"Deleting existing PDF at {static_pdf_path}")
        #     os.remove(static_pdf_path)
        logging.info(f"Moving PDF {pdf_path} to {static_pdf_path}")
        shutil.copy2(pdf_path, static_pdf_path)
        logging.info(f"PDF moved successfully from {pdf_path} to {static_pdf_path}")
    except Exception as e:
        logging.error(f"Failed to move PDF {pdf_path} to {static_pdf_path}: {e}")

    filename = os.path.splitext(os.path.basename(pdf_path))[0]
    yaml_properties = get_yaml_properties(filename)
    
    with open(markdown_path, 'w', encoding='utf-8') as md_file:
        # Write YAML front matter
        md_file.write('---\n')
        for key, value in yaml_properties.items():
            if isinstance(value, list):
                md_file.write(f"{key}: [{', '.join(value)}]\n")
            else:
                md_file.write(f"{key}: {value}\n")
        md_file.write('---\n\n')
        
        md_file.write(f"# {filename}\n\n")
        md_file.write("# Extracted\n\n")
        md_file.write(text)
        md_file.write(f"**Original PDF:** ![[{filename}.pdf]]\n\n")

    logging.info(f"Markdown note created: {markdown_path}")

def load_json_log(json_log_path):
    if os.path.exists(json_log_path):
        with open(json_log_path, 'r') as log_file:
            return json.load(log_file)
    return {}

def save_json_log(json_log_path, log_data):
    with open(json_log_path, 'w') as log_file:
        json.dump(log_data, log_file, indent=4)

def process_pdfs_in_folder(folder, vault_base_path, vault_static_path, json_log_path):
    log_data = load_json_log(json_log_path)
    existing_markdown_files = {}
    for root, _, files in os.walk(vault_base_path):
        logging.info(f"Processing folder: {root}")
        logging.info(f"_: {_}")
        logging.info(f"files: {files}")
        for filename in files:
            if filename.endswith(".md"):
                base_filename = os.path.splitext(filename)[0]
                existing_markdown_files[base_filename] = os.path.join(root, filename)

    for root, _, files in os.walk(folder):
        for filename in files:
            if filename.endswith(".pdf") and "books" not in root:
                pdf_path = os.path.join(root, filename)
                file_mod_time = os.path.getmtime(pdf_path)
                base_filename = os.path.splitext(filename)[0]

                # Check if the file has been modified since the last recorded time
                if base_filename not in log_data or file_mod_time > log_data[base_filename]:
                    logging.info(f"Processing {pdf_path}...")
                    try:
                        if base_filename in existing_markdown_files:
                            markdown_path = existing_markdown_files[base_filename]
                            logging.info(f"Updating existing Markdown note: {markdown_path}")
                        else:
                            markdown_path = os.path.join(vault_base_path, f"{base_filename}.md")
                            logging.info(f"Creating new Markdown note: {markdown_path}")
                        
                        static_pdf_path = os.path.join(vault_static_path, f"{base_filename}.pdf")

                        text = ocr_and_extract_text(pdf_path)
                        create_markdown_note_in_obsidian(pdf_path, text, markdown_path, static_pdf_path)
                        
                        # Update the log data with the new modification time
                        log_data[base_filename] = file_mod_time
                    except subprocess.CalledProcessError:
                        logging.error(f"Failed to process {pdf_path}")

    # Save the updated log data
    save_json_log(json_log_path, log_data)

def main():
    # Perform OCR and create/update Markdown notes for PDFs in the Google Drive path
    process_pdfs_in_folder(GOOGLE_DRIVE_PATH, OBSIDIAN_BASE_PATH, OBSIDIAN_STATIC_PATH, JSON_LOG_PATH)
    
    # Log the sync summary
    with open(SYNC_SUMMARY_LOG, 'a') as summary_log:
        summary_log.write(f"Sync summary logged on {datetime.now()}\n")

if __name__ == "__main__":
    main()