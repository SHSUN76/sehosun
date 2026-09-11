# origin

정리된 csv/xlsx 데이터로 OriginLab 논문급 그래프를 만들고, PowerPoint에 편집 가능한 OLE 객체로 붙이는 워크플로 스킬. 스타일은 donor `.opj` 10종(bar_labeled, bar_grouped, double_y, broken_axis, log_axis, waterfall, line_symbol, errorbar, annotated, floating_bar)에서 상속하고 house style을 강제 적용한다.

## 설치

```bash
claude plugin marketplace add SHSUN76/sehosun
claude plugin install origin@sehosun
```

## 전제 조건

- **Origin 2021 설치 필수** (`Origin64.exe`). `originpro`는 Origin의 COM 서버에 붙는 래퍼일 뿐이며 Origin을 대신하지 않는다. Origin이 없으면 `recover.py`(pptx OLE → `.opj` 복원) 외에는 돌지 않는다.
- Windows + COM. 실행 중인 Origin·PowerPoint는 닫아 둔다(단일 인스턴스라 사용자 작업을 덮어쓴다). 병렬 실행 금지.
- 파이썬 패키지:

```bash
pip install originpro pandas PyYAML olefile Pillow numpy
```

## 사용

"이 데이터로 Origin 그래프 만들어줘", "논문 figure 만들어줘", "그래프 PPT로 붙여줘" 같은 요청에 자동 트리거된다.

MIT License · Seho Sun (CAMP Lab, Yeungnam University)
