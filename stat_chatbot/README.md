# 📊 통계 챗봇 (Statistical Chatbot)

강의노트를 기반으로 한 RAG(Retrieval-Augmented Generation) 챗봇입니다. 통계학 관련 질문에 강의노트 내용을 바탕으로 답변합니다.

## 🚀 기능

- **RAG 기반 답변**: 강의노트에서 관련 내용을 검색하여 정확한 답변 제공
- **출처 표시**: 답변의 근거가 되는 강의노트 표시
- **Streamlit UI**: 사용자 친화적인 웹 인터페이스
- **FAISS 벡터DB**: 빠른 검색을 위한 로컬 벡터 데이터베이스

## 📋 필수 요구사항

- Python 3.8+
- OpenAI API 키

## ⚙️ 설치

1. 의존성 설치
```bash
pip install -r requirements.txt
```

2. 환경 변수 설정
```bash
cp .env.example .env
# .env 파일에 OpenAI API 키 입력
```

## 🏃 실행

```bash
streamlit run app.py
```

그러면 브라우저에서 `http://localhost:8501`에 앱이 열립니다.

## 📁 프로젝트 구조

```
stat_chatbot/
├── app.py              # Streamlit 앱
├── chatbot.py          # RAG 챗봇 로직
├── loader.py           # 강의노트 로더
├── requirements.txt    # 의존성
├── .env.example        # 환경 변수 예시
├── README.md          # 이 파일
└── data/
    └── vector_store/   # FAISS 벡터DB (자동 생성)
```

## 🔧 주요 클래스 및 함수

### `loader.py`
- `load_qmd_files()`: QMD 파일 로드
- `extract_title()`: 문서 제목 추출
- `clean_content()`: 내용 정제
- `chunk_documents()`: 문서 청킹

### `chatbot.py`
- `StatChatbot`: RAG 챗봇 클래스
  - `build_vector_store()`: 벡터스토어 구축
  - `setup_qa_chain()`: QA 체인 설정
  - `query()`: 질문 처리

### `app.py`
- Streamlit 기반 웹 UI
- 대화형 인터페이스
- 설정 및 벡터스토어 관리

## 💻 사용 예시

```python
from chatbot import StatChatbot
import os
from dotenv import load_dotenv

load_dotenv()

# 챗봇 초기화
chatbot = StatChatbot()

# 벡터스토어 구축
chatbot.build_vector_store()

# QA 체인 설정
chatbot.setup_qa_chain()

# 질문하기
answer, sources = chatbot.query("회귀분석이란 무엇인가요?")
print(answer)
for source in sources:
    print(f"- {source['title']} ({source['category']})")
```

## 🔄 벡터스토어 업데이트

새로운 강의노트가 추가된 경우:
```python
chatbot.build_vector_store(force_rebuild=True)
```

또는 Streamlit UI에서 "벡터스토어 재생성" 버튼 클릭

## 📊 강의노트 카테고리

- 기초수학 (`math/`)
- 수리통계 (`math_stat/`)
- 조사방법론 (`survey/`)
- 기초통계 (`intro_stat/`)
- 회귀분석 (`linear_model/`)
- 다변량분석 (`mda/`)
- 머신러닝·딥러닝 (`mldl_*/`)
- 인공지능·감성분석 (`inference_xai/`, `sentiment_analysis/`)
- 데이터 축약 (`data_reduction/`)

## 🚀 배포

### Streamlit Cloud에서 배포

1. GitHub에 리포지토리 푸시
2. [Streamlit Cloud](https://share.streamlit.io/)에서 새 앱 생성
3. 리포지토리와 파일 선택
4. Secrets에 `OPENAI_API_KEY` 추가

### Docker로 배포

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py"]
```

## 🐛 문제 해결

**Q: "OPENAI_API_KEY not found" 에러**
- A: `.env` 파일에 API 키가 설정되었는지 확인하세요.

**Q: 벡터스토어 생성이 느려요**
- A: 첫 실행 시 임베딩 생성에 시간이 걸립니다. 이후는 저장된 스토어를 사용합니다.

**Q: 답변이 부정확해요**
- A: 더 구체적인 질문을 해보세요. 강의노트에 없는 내용은 답변할 수 없습니다.

## 📝 라이선스

이 프로젝트는 [MIT License](LICENSE)를 따릅니다.

## 👥 기여

피드백과 개선 제안은 언제든 환영합니다!
