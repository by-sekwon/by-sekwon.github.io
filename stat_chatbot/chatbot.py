"""
RAG Chatbot using LangChain and FAISS
"""
import os
from typing import List, Tuple
from pathlib import Path
import pickle

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA

from loader import load_qmd_files, chunk_documents, clean_content


class StatChatbot:
    """Statistical Chatbot using RAG"""
    
    def __init__(self, notes_dir: str = "../notes", api_key: str = None):
        """
        Initialize the chatbot
        
        Args:
            notes_dir: Path to notes directory
            api_key: OpenAI API key
        """
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
        
        self.notes_dir = notes_dir
        self.embeddings = None
        self.vector_store = None
        self.qa_chain = None
        self.documents = []
        
    def build_vector_store(self, force_rebuild: bool = False):
        """
        Build FAISS vector store from lecture notes
        
        Args:
            force_rebuild: Force rebuild even if exists
        """
        db_path = Path("data/vector_store")
        
        if db_path.exists() and not force_rebuild:
            print("Loading existing vector store...")
            self.embeddings = OpenAIEmbeddings()
            self.vector_store = FAISS.load_local("data/vector_store", self.embeddings)
            return
        
        print("Building vector store from lecture notes...")
        
        # Initialize embeddings
        self.embeddings = OpenAIEmbeddings()
        
        # Load documents
        documents = load_qmd_files(self.notes_dir)
        print(f"Loaded {len(documents)} documents")
        
        # Convert to LangChain Document format
        lang_docs = [
            Document(
                page_content=doc["content"],
                metadata={
                    "title": doc["title"],
                    "category": doc["category"],
                    "source": doc["source"],
                    "file_path": doc["file_path"]
                }
            )
            for doc in documents
        ]
        
        # Split text
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", " "]
        )
        
        split_docs = text_splitter.split_documents(lang_docs)
        print(f"Split into {len(split_docs)} chunks")
        
        # Create FAISS vector store
        self.vector_store = FAISS.from_documents(split_docs, self.embeddings)
        
        # Save vector store
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_store.save_local("data/vector_store")
        print(f"Vector store saved to {db_path}")
        
    def setup_qa_chain(self):
        """Setup QA chain"""
        if not self.vector_store:
            raise ValueError("Vector store not built. Call build_vector_store() first.")
        
        llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0.7)
        
        prompt_template = """당신은 통계학 강의 도우미입니다. 
        
다음의 강의 자료를 바탕으로 질문에 답변해주세요.
질문에 대한 답변이 자료에 없으면 "이 주제에 대해서는 강의 자료에 자세한 설명이 없습니다"라고 답변해주세요.

강의 자료:
{context}

질문: {question}

답변:"""
        
        prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=self.vector_store.as_retriever(search_kwargs={"k": 3}),
            chain_type_kwargs={"prompt": prompt},
            return_source_documents=True
        )
    
    def query(self, question: str) -> Tuple[str, List[dict]]:
        """
        Query the chatbot
        
        Args:
            question: User question
            
        Returns:
            Tuple of (answer, source_documents)
        """
        if not self.qa_chain:
            self.setup_qa_chain()
        
        result = self.qa_chain({"query": question})
        
        sources = []
        for doc in result.get("source_documents", []):
            sources.append({
                "title": doc.metadata.get("title"),
                "category": doc.metadata.get("category"),
                "source": doc.metadata.get("source"),
                "snippet": doc.page_content[:200] + "..."
            })
        
        return result["result"], sources


if __name__ == "__main__":
    # Test
    import dotenv
    dotenv.load_dotenv()
    
    chatbot = StatChatbot()
    chatbot.build_vector_store()
    chatbot.setup_qa_chain()
    
    # Test query
    answer, sources = chatbot.query("회귀분석이란 무엇인가요?")
    print(f"Answer: {answer}")
    print(f"\nSources:")
    for source in sources:
        print(f"  - {source['title']} ({source['category']})")
