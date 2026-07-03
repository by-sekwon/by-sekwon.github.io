"""
Streamlit app for Statistical Chatbot
"""
import streamlit as st
import os
from pathlib import Path
from dotenv import load_dotenv

from chatbot import StatChatbot

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
    .stChatMessage {
        padding: 1rem;
        border-radius: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "chatbot" not in st.session_state:
    st.session_state.chatbot = None
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
            
            chatbot = StatChatbot(api_key=api_key)
            chatbot.build_vector_store()
            chatbot.setup_qa_chain()
            
            st.session_state.chatbot = chatbot
            st.session_state.initialized = True
            st.success("✅ 준비가 완료되었습니다!")
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
        1. 우측 하단의 'AI 기능 활성화' 버튼으로 챗봇을 시작하세요.
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
                answer, sources = st.session_state.chatbot.query(user_input)
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
        
        if st.button("🔄 벡터스토어 재생성", use_container_width=True):
            with st.spinner("벡터스토어를 재생성 중입니다..."):
                st.session_state.chatbot.build_vector_store(force_rebuild=True)
                st.success("✅ 재생성 완료")
        
        st.markdown("---")
        st.markdown("## 📚 사용 가능한 강의 주제")
        st.markdown("""
        - 기초수학
        - 수리통계
        - 조사방법론
        - 기초통계
        - 회귀분석
        - 다변량분석
        - 머신러닝·딥러닝
        - 인공지능·감성분석
        """)
        
        st.markdown("---")
        st.markdown("## 💡 팁")
        st.markdown("""
        - 구체적인 질문이 더 정확한 답변을 받을 수 있습니다.
        - 강의노트에 있는 내용에 대해 질문하세요.
        - 여러 번 질문하며 대화를 이어갈 수 있습니다.
        """)


if __name__ == "__main__":
    main()
