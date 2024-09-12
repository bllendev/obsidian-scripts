import os
import shutil
import yaml
import re
import json
import pprint
import logging

# Set up logging to print to the console and to a file
LOG_FILE_PATH = '/app/logs/sync_reporty_wiki.log'
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(LOG_FILE_PATH),
    logging.StreamHandler()
])


# Define your paths
OBSIDIAN_VAULT_PATH = os.getenv(f"OBSIDIAN_VAULT_PATH")
GITHUB_WIKI_PATH = os.getenv("GITHUB_WIKI_PATH")
MAPPING_FILE_PATH = os.path.join(GITHUB_WIKI_PATH, 'file_mapping.json')
FILE_NAME_FILTER_WORD_OUT = "software-"  # if your files have a naming pattern and you want to filter pattern out for unique names
TARGET_TAGS = {'reporty'}  # add the tags or properties you want to check for
TARGET_TYPE = 'sync-docs'  # a check if your markdown has some front matter you want to check for


def read_yaml_frontmatter(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        frontmatter_match = re.match(r'^---(.*?)---', content, re.DOTALL)
        if frontmatter_match:
            frontmatter = frontmatter_match.group(1)
            return yaml.safe_load(frontmatter)
    return {}

def should_copy_file(frontmatter):
    if frontmatter.get('type') == TARGET_TYPE:
        try:
            for key, value in frontmatter.items():
                if isinstance(value, list) and any(tag in TARGET_TAGS for tag in value):
                    logging.info(f"File will be copied based on tags in list for key {key}")
                    return True
                if key in TARGET_TAGS or (isinstance(value, str) and value in TARGET_TAGS):
                    logging.info(f"File will be copied based on tag in key {key} or value {value}")
                    return True
        except Exception as e:
            logging.error(f"Error checking frontmatter: {e}")
    return False

def find_embedded_files(markdown_content):
    embedded_files = re.findall(r'!\[\[(.*?)\]\]', markdown_content)  # Embedded files with ![[]]
    embedded_files += re.findall(r'\[\[(.*?)\]\]', markdown_content)  # Links with [[]]
    logging.info(f"Found embedded files and links: {embedded_files}")
    embedded_files = [embedded_file.split(f"|")[0] for embedded_file in embedded_files]
    return embedded_files

def copy_file(abs_path, vault_path, wiki_path, copied_files):
    if os.path.exists(abs_path) and abs_path not in copied_files:
        rel_path = os.path.relpath(abs_path, vault_path)
        slugified_filename = slugify(os.path.splitext(rel_path)[0]) + os.path.splitext(abs_path)[1]
        dest_path = os.path.join(wiki_path, slugified_filename)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(abs_path, dest_path)
        logging.info(f"Copied file {abs_path} to {dest_path}")
        copied_files.add(abs_path)
        return slugified_filename
    return None

def load_mapping(file_path):
    logging.debug(f"Loading file mapping from {file_path}")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_mapping(mapping, file_path):
    logging.debug(f"Saving file mapping to {file_path}")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=4)

def slugify(title):
    logging.debug(f"Slugifying title: {title}")
    
    # split the title into name and extension
    name, ext = os.path.splitext(title)
    
    # slugify only the name
    slug = re.sub(r'[^\w]+', '-', name).strip('-').lower()
    
    # reattatch the extension
    slugified_title = f"{slug}{ext}"
    
    logging.debug(f"Slugified title: {slugified_title}")
    return slugified_title

def transform_obsidian_links(content):
    # transform embedded files in the markdown
    content = re.sub(r'!\[\[(.*?)\]\]', lambda m: f'![{m.group(1).split("|")[0]}](./{slugify(m.group(1).split("|")[0]).replace(FILE_NAME_FILTER_WORD_OUT, "")})', content)

    # transform links
    content = re.sub(r'\[\[(.*?)\]\]', lambda m: f'[{m.group(1).split("|")[0]}](./{slugify(m.group(1).split("|")[0]).replace("FILE_NAME_FILTER_WORD_OUT", "")})', content)
    
    # handle image file types !
    if "-png" in content:
        content = content.replace("-png", ".png")
    if "-svg" in content:
        content = content.replace("-svg", ".svg")
    if "-jpg" in content:
        content = content.replace("-jpg", ".jpg")
    if "-jpeg" in content:
        content = content.replace("-jpeg", ".jpeg")
    if "-pdf" in content:
        content = content.replace("-pdf", ".pdf")

    # remove Excalidraw data section
    content = re.sub(r'# Excalidraw Data.*', '', content, flags=re.DOTALL)
    return content

def copy_markdown_files(vault_path, wiki_path, mapping, copied_files):
    new_mapping = {}
    references = set()
    for root, _, files in os.walk(vault_path):
        for file in files:
            if file.endswith('.md'):
                file_path = os.path.join(root, file)
                frontmatter = read_yaml_frontmatter(file_path)
                if should_copy_file(frontmatter):
                    logging.info(f"Copying {file_path}")
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    embedded_files = find_embedded_files(content)
                    # Collect full path references
                    file_path = os.path.join(root, file)
                    logging.warning(f"file_path: {file_path}")

                    for embedded_file in embedded_files:
                        if file in embedded_file:
                            references.add(file_path)
                    content = transform_obsidian_links(content)  # transform Obsidian links to wiki links
                    relative_path = os.path.relpath(file_path, vault_path)
                    slugified_filename = slugify(os.path.splitext(relative_path)[0]) + '.md'
                    slugified_filename = slugified_filename.replace("FILE_NAME_FILTER_WORD_OUT", "")
                    dest_path = os.path.join(wiki_path, slugified_filename)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(dest_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logging.info(f"Copied {file_path} to {dest_path}")
                    new_mapping[relative_path] = slugified_filename
                    copied_files.add(file_path)

    logging.debug("--------------------------------------------")
    logging.debug(f"New mapping: {pprint.pformat(new_mapping)}")
    logging.debug(f"references: {pprint.pformat(references)}")
    logging.debug(f"copied_files: {pprint.pformat(copied_files)}")
    return new_mapping, references

def copy_referenced_files(vault_path, wiki_path, references, copied_files):
    logging.debug(
        f"Copying referenced files: {pprint.pformat(vault_path)} \n"
        f"{pprint.pformat(wiki_path)} \n {pprint.pformat(references)} \n {pprint.pformat(copied_files)}"
    )
    for ref in references:
        if "static" not in ref:
            abs_path = os.path.join(vault_path, ref)

        abs_path = abs_path.replace("/", "\\")

        logging.info(f"abs_path: {abs_path}")
        if os.path.exists(abs_path):
            logging.warning(f"Referenced file {abs_path} exists!!!!")
            slugified_filename = slugify(os.path.splitext(ref)[0]).replace("FILE_NAME_FILTER_WORD_OUT", "") + os.path.splitext(ref)[1]
            dest_path = os.path.join(wiki_path, slugified_filename)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(abs_path, dest_path)
            logging.info(f"Copied referenced file {abs_path} to {dest_path}")
            copied_files.add(abs_path)
        else:
            logging.warning(f"Referenced file {abs_path} does not exist")

def update_links(wiki_path):
    for root, _, files in os.walk(wiki_path):
        for file in files:
            if file.endswith('.md'):
                file_path = os.path.join(root, file)
                logging.debug(f"Updating links in file: {file_path}")
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', lambda m: f"[{m.group(1)}]({m.group(2)})" if not m.group(2).startswith('http') else m.group(0), content)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logging.info(f"Updated links in {file_path}")

def delete_removed_files(old_mapping, new_mapping, wiki_path):
    for relative_path in old_mapping:
        if relative_path not in new_mapping:
            file_path = os.path.join(wiki_path, old_mapping[relative_path])
            if os.path.exists(file_path):
                os.remove(file_path)
                logging.info(f"Deleted {file_path} as it no longer exists in the vault")

def copy_static_files(vault_path, wiki_path, copied_files):
    static_path = os.path.join(vault_path, 'static')
    if os.path.exists(static_path):
        for root, _, files in os.walk(static_path):
            for file in files:
                abs_path = os.path.join(root, file)
                not_script = "script" not in abs_path.lower()
                not_downloaded = "downloaded" not in abs_path.lower()
                not_korean = "korean" not in abs_path.lower()
                if abs_path not in copied_files and not_script and not_downloaded and not_korean:
                    rel_path = os.path.relpath(abs_path, static_path)
                    dest_path = os.path.join(wiki_path, rel_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy2(abs_path, dest_path)
                    logging.info(f"Copied static file {abs_path} to {dest_path}")
                    copied_files.add(abs_path)

def main():
    old_mapping = load_mapping(MAPPING_FILE_PATH)
    copied_files = set()
    new_mapping, references = copy_markdown_files(OBSIDIAN_VAULT_PATH, GITHUB_WIKI_PATH, old_mapping, copied_files)
    copy_referenced_files(OBSIDIAN_VAULT_PATH, GITHUB_WIKI_PATH, references, copied_files)
    update_links(GITHUB_WIKI_PATH)
    delete_removed_files(old_mapping, new_mapping, GITHUB_WIKI_PATH)
    copy_static_files(OBSIDIAN_VAULT_PATH, GITHUB_WIKI_PATH, copied_files)
    save_mapping(new_mapping, MAPPING_FILE_PATH)
    logging.info("All files copied, links updated, and old files deleted.")

if __name__ == "__main__":
    main()
