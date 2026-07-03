#!/usr/bin/env python3
"""
강의노트를 JSON으로 변환하는 스크립트
"""
import json
import re
from pathlib import Path

def extract_title(content, file_path):
    """QMD 파일에서 제목 추출"""
    # YAML front matter에서 title 찾기
    yaml_match = re.search(r'title:\s*["\']?([^"\'\n]+)["\']?', content)
    if yaml_match:
        return yaml_match.group(1).strip()
    
    # # 헤더에서 찾기
    header_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if header_match:
        return header_match.group(1).strip()
    
    # 파일명 사용
    return file_path.stem.replace('_', ' ').title()

def clean_content(content):
    """QMD 파일 내용 정제"""
    # YAML front matter 제거
    content = re.sub(r'^---\n.*?---\n', '', content, flags=re.DOTALL)
    
    # 코드 블록 제거 (내용도 제거)
    content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
    
    # 백틱 제거 (인라인 코드)
    content = re.sub(r'`([^`]+)`', r'\1', content)
    
    # HTML 주석 제거
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    
    # 마크다운 링크를 텍스트로 변환
    content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
    
    # 과도한 공백 제거
    content = re.sub(r'\n\s*\n+', '\n\n', content)
    
    # 앞뒤 공백 제거
    content = content.strip()
    
    return content

def load_lecture_notes():
    """강의노트 로드"""
    notes_dir = Path('notes')
    cwd = Path.cwd()
    documents = []
    
    for qmd_file in sorted(notes_dir.rglob('*.qmd')):
        try:
            content = qmd_file.read_text(encoding='utf-8')
            category = qmd_file.parent.name
            title = extract_title(content, qmd_file)
            cleaned_content = clean_content(content)
            
            if cleaned_content and len(cleaned_content) > 50:  # 최소 길이 확인
                documents.append({
                    'title': title,
                    'category': category,
                    'content': cleaned_content,
                    'source': qmd_file.name,
                    'path': str(qmd_file)
                })
        except Exception as e:
            print(f"Error processing {qmd_file}: {e}")
    
    return documents

def main():
    """메인 함수"""
    print("📚 강의노트 로딩 중...")
    documents = load_lecture_notes()
    print(f"✅ {len(documents)}개의 강의노트 로드 완료")
    
    # JSON 저장
    output_file = Path('docs/lecture_notes.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(documents, f, ensure_ascii=False, indent=2)
    
    print(f"💾 {output_file}에 저장 완료")
    
    # 카테고리별 통계
    categories = {}
    for doc in documents:
        cat = doc['category']
        categories[cat] = categories.get(cat, 0) + 1
    
    print("\n📊 카테고리별 강의노트:")
    for cat, count in sorted(categories.items()):
        print(f"  - {cat}: {count}개")

if __name__ == '__main__':
    main()
