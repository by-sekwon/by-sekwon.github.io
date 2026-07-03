"""
Streamlit app for Statistical Chatbot - Simplified Version
"""
import streamlit as st
import os
from pathlib import Path
from dotenv import load_dotenv

from chatbot import SimpleChatbot
from loader import load_qmd_files

# Load environment variables
load_dotenv()

# Configure page
st.set_page_config(
    page_title="통계 챗봇",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main {
        padding: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "chatbot" not in st.session_state:
    st.session_state.chatbot = None
    st.session_state.documents = None
    st.session_state.initialized = False

if "messages" not in st.session_state:
    st.session_state.messages = []


def initialize_chatbot():
    """Initialize the chatbot"""
    with st.spinner("📚 강의노트를 로딩 중입니다..."):
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                st.error("❌ OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
                return False
            
            chatbot = SimpleChatbot(api_key=api_key)
            documents = chatbot.load_documents("../notes")
            
            if not documents:
                st.error("❌ 강의노트를 로드할 수 없습니다.")
                return False
            
            st.session_state.chatbot = chatbot
            st.session_state.documents = documents
            st.session_state.initialized = True
            st.success(f"✅ {len(documents)}개의 강의노트가 준비되었습니다!")
            return True
        except Exception as e:
            st.error(f"❌ 초기화 중 오류 발생: {str(e)}")
            return False


def main():
    # Header
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown("# 📊")
    with col2:
        st.markdown("# 통계 챗봇")
        st.markdown("강의노트 기반 통계 질문 답변 시스템")
    
    st.markdown("---")
    
    # Initialize chatbot if not done
    if not st.session_state.initialized:
        if st.button("🚀 챗봇 시작하기", use_container_width=True, key="init_btn"):
            initialize_chatbot()
        st.info("""
        ### 사용 방법
        1. '챗봇 시작하기' 버튼을 클릭하세요.
        2. 통계학 관련 질문을 입력하세요.
        3. 강의노트 기반의 답변을 받을 수 있습니다.
        
        ### 주의사항
        - OpenAI API 키가 필요합니다.
        - 첫 실행 시 강의노트 처리에 시간이 걸릴 수 있습니다.
        """)
        return
    
    # Chat interface
    st.subheader("💬 질문하기")
    
    # Display chat history
    chat_container = st.container()
    with chat_container:
        for message in st.session_state.messages:
            if message["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(message["content"])
            else:
                with st.chat_message("assistant"):
                    st.markdown(message["content"])
                    if message.get("sources"):
                        with st.expander("📖 참고 자료"):
                            for source in message["sources"]:
                                st.markdown(f"""
                                **{source['title']}** ({source['category']})
                                
                                *{source['snippet']}*
                                """)
    
    # Input
    st.markdown("---")
    col1, col2 = st.columns([1, 0.15])
    
    with col1:
        user_input = st.chat_input("질문을 입력하세요...")
    
    with col2:
        if st.button("🔄", help="초기화"):
            st.session_state.messages = []
            st.rerun()
    
    # Process user input
    if user_input:
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })
        
        # Get chatbot response
        with st.spinner("⏳ 답변을 생성 중입니다..."):
            try:
                answer, sources = st.session_state.chatbot.query(
                    user_input, 
                    st.session_state.documents
                )
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "sources": sources
                })
                st.rerun()
            except Exception as e:
                st.error(f"❌ 오류 발생: {str(e)}")
    
    # Sidebar
    with st.sidebar:
        st.markdown("## ⚙️ 설정")
        st.markdown("---")
        
        st.markdown("### 📊 통계 정보")
        if st.session_state.documents:
            st.markdown(f"**로드된 강의노트:** {len(st.session_state.documents)}개")
            
            categories = {}
            for doc in st.session_state.documents:
                cat = doc.get("category", "기타")
                categories[cat] = categories.get(cat, 0) + 1
            
            st.markdown("**카테고리별 강의노트:**")
            for cat, count in sorted(categories.items()):
                st.markdown(f"- {cat}: {count}개")
        
        st.markdown("---")
        st.markdown("## 💡 팁")
        st.markdown("""
        - 구체적인 질문이 더 정확한 답변을 받을 수 있습니다.
        - 강의노트에 있는 내용에 대해 질문하세요.
        - 여러 번 질문하며 대화를 이어갈 수 있습니다.
        """)


if __name__ == "__main__":
    main()

