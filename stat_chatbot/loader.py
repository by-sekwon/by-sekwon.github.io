"""
Load and process Quarto markdown files for RAG chatbot
"""
import os
from pathlib import Path
from typing import List, Dict
import re


def load_qmd_files(notes_dir: str) -> List[Dict[str, str]]:
    """
    Load all .qmd files from the notes directory
    
    Args:
        notes_dir: Path to the notes directory
        
    Returns:
        List of documents with content and metadata
    """
    documents = []
    notes_path = Path(notes_dir)
    
    if not notes_path.exists():
        raise FileNotFoundError(f"Notes directory not found: {notes_dir}")
    
    # Find all .qmd files
    qmd_files = list(notes_path.rglob("*.qmd"))
    print(f"Found {len(qmd_files)} QMD files")
    
    for qmd_file in qmd_files:
        try:
            with open(qmd_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract title from the file
            title = extract_title(content, qmd_file.stem)
            
            # Extract category from path
            category = qmd_file.parent.name
            
            # Clean content (remove YAML front matter and code blocks)
            cleaned_content = clean_content(content)
            
            if cleaned_content.strip():  # Only add if has content
                documents.append({
                    "content": cleaned_content,
                    "title": title,
                    "category": category,
                    "file_path": str(qmd_file),
                    "source": qmd_file.stem
                })
        except Exception as e:
            print(f"Error loading {qmd_file}: {e}")
    
    return documents


def extract_title(content: str, default_title: str) -> str:
    """
    Extract title from QMD file
    """
    # Try to find # header
    lines = content.split('\n')
    for line in lines:
        if line.strip().startswith('#') and not line.strip().startswith('##'):
            return line.replace('#', '').strip()
    
    # Try YAML title
    yaml_match = re.search(r'title:\s*["\']?([^"\'\n]+)["\']?', content)
    if yaml_match:
        return yaml_match.group(1)
    
    return default_title


def clean_content(content: str) -> str:
    """
    Clean QMD content by removing YAML front matter and code blocks
    """
    # Remove YAML front matter
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2]
    
    # Remove code blocks but keep the content explanation
    # Remove inline code references
    content = re.sub(r'```[\s\S]*?```', '', content)
    content = re.sub(r'`[^`]+`', '', content)
    
    # Remove HTML comments
    content = re.sub(r'<!--[\s\S]*?-->', '', content)
    
    # Remove excessive whitespace
    content = '\n'.join(line.strip() for line in content.split('\n') if line.strip())
    
    return content


def chunk_documents(documents: List[Dict], chunk_size: int = 500, overlap: int = 100) -> List[Dict]:
    """
    Split documents into chunks for better embedding
    
    Args:
        documents: List of documents
        chunk_size: Number of characters per chunk
        overlap: Number of overlapping characters between chunks
        
    Returns:
        List of chunked documents
    """
    chunked_docs = []
    
    for doc in documents:
        content = doc["content"]
        sentences = content.split('.')
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < chunk_size:
                current_chunk += sentence + ". "
            else:
                if current_chunk.strip():
                    chunked_docs.append({
                        "content": current_chunk.strip(),
                        "title": doc["title"],
                        "category": doc["category"],
                        "source": doc["source"],
                        "file_path": doc["file_path"]
                    })
                current_chunk = sentence + ". "
        
        if current_chunk.strip():
            chunked_docs.append({
                "content": current_chunk.strip(),
                "title": doc["title"],
                "category": doc["category"],
                "source": doc["source"],
                "file_path": doc["file_path"]
            })
    
    print(f"Created {len(chunked_docs)} chunks from {len(documents)} documents")
    return chunked_docs


if __name__ == "__main__":
    # Test
    docs = load_qmd_files("../notes")
    print(f"Loaded {len(docs)} documents")
    if docs:
        print(f"First doc: {docs[0]['title']}")
    
    chunked = chunk_documents(docs)
    print(f"Total chunks: {len(chunked)}")
