"""
Simplified RAG Chatbot using OpenAI API and FAISS
"""
import os
from typing import List, Tuple
from pathlib import Path
import json

import openai
from loader import load_qmd_files

try:
    from faiss_cpu import FAISS
except:
    try:
        from faiss import FAISS
    except:
        FAISS = None


class SimpleChatbot:
    """Simplified Statistical Chatbot"""
    
    def __init__(self, api_key: str = None):
        """
        Initialize the chatbot
        
        Args:
            api_key: OpenAI API key
        """
        if api_key:
            openai.api_key = api_key
        else:
            openai.api_key = os.getenv("OPENAI_API_KEY")
    
    def load_documents(self, notes_dir: str = "../notes") -> List[dict]:
        """Load lecture notes"""
        try:
            documents = load_qmd_files(notes_dir)
            print(f"Loaded {len(documents)} documents")
            return documents
        except Exception as e:
            print(f"Error loading documents: {e}")
            return []
    
    def query(self, question: str, documents: List[dict], top_k: int = 3) -> Tuple[str, List[dict]]:
        """
        Query the chatbot
        
        Args:
            question: User question
            documents: List of documents
            top_k: Number of top documents to retrieve
            
        Returns:
            Tuple of (answer, source_documents)
        """
        if not documents:
            return "강의 자료를 로드할 수 없습니다.", []
        
        # Simple keyword matching for document retrieval
        question_lower = question.lower()
        scored_docs = []
        
        for doc in documents:
            content_lower = doc["content"].lower()
            score = sum(1 for word in question_lower.split() if word in content_lower)
            if score > 0:
                scored_docs.append((doc, score))
        
        # Sort by score and get top documents
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        top_docs = [doc for doc, _ in scored_docs[:top_k]]
        
        if not top_docs:
            # Return any document if no matches
            top_docs = documents[:top_k]
        
        # Prepare context
        context = "\n\n".join([
            f"[{doc['title']} - {doc['category']}]\n{doc['content'][:300]}"
            for doc in top_docs
        ])
        
        # Create prompt
        prompt = f"""당신은 통계학 강의 도우미입니다.

다음의 강의 자료를 바탕으로 질문에 답변해주세요.
질문에 대한 답변이 자료에 없으면 "이 주제에 대해서는 강의 자료에 자세한 설명이 없습니다"라고 답변해주세요.

강의 자료:
{context}

질문: {question}

답변:"""
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )
            answer = response.choices[0].message.content
        except Exception as e:
            answer = f"답변 생성 중 오류가 발생했습니다: {str(e)}"
        
        # Format sources
        sources = [
            {
                "title": doc["title"],
                "category": doc["category"],
                "source": doc["source"],
                "snippet": doc["content"][:200] + "..."
            }
            for doc in top_docs
        ]
        
        return answer, sources


if __name__ == "__main__":
    # Test
    from dotenv import load_dotenv
    load_dotenv()
    
    chatbot = SimpleChatbot()
    docs = chatbot.load_documents()
    
    if docs:
        answer, sources = chatbot.query("회귀분석이란 무엇인가요?", docs)
        print(f"Answer: {answer}")
        print(f"\nSources:")
        for source in sources:
            print(f"  - {source['title']} ({source['category']})")

