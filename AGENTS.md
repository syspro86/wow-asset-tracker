## 프로젝트의 목표

1. 프로그램은 python을 사용하여 작성한다.
2. WOW TradeSkillMaster Addon 설정파일을 통해, WOW 자산 정보를 추출하고 JSON FILE 형태로 정리하여 저장한다.
3. 일별 총 골드 정보를 추출하여 일자 별로 저장한다.
    1. 은행 골드 보유량도 구분하여 일자 별로 저장한다.
    2. 총 골드 보유량도 구분하여 일자 별로 저장한다.
    3. 캐릭터별 골드 보유량도 구분하여 일자 별로 저장한다.
    4. 캐릭터별/은행 골드 보유량은 변경량이 있을 때만 정보가 남기 때문에, 일별로 정보가 없는 경우 직전 보유량을 합산해야 한다.
4. 전문기술을 통해 주문제작한 내역을 추출하여 별도로 저장한다.

## 프로젝트의 입력과 출력 정보

1. 입력 설정 파일 경로를 --lua-path 파라미터 또는 .env 파일의 LUA_PATH 환경변수에 지정한다.
2. 출력 경로는 --output-path 파라미터 또는 .env 파일의 OUTPUT_PATH 환경변수에 지정한다.
3. 일별 골드 정보는 $output-path/gold/YYYY/MM/DD.json 경로에 저장한다. 캐릭터별 그리고 warbank의 골드 정보를 모두 포함한다. 골드 미만의 실버/코퍼 정보는 포함하지 않는다. 캐릭터 목록에는 "캐릭명-서버명" 형태로 기록한다.
4. 일별 주문제작에 정보는 $output-path/crafting/YYYY/MM/DD.json 에 저장한다. 이 때 YYYYMMDD 는 수행한 일자가 아닌 주문제작한 기록 일자로 한다.
5. 주문제작에 대한 내역을 주문요청자 별로 정리하여 $output-path/crafting/서버명/캐릭명.json 형태로 저장한다. 제작 아이템과 수수료, 제작자 캐릭명, 제작자 서버명 정보를 기록한다. 주문 요청자 서버 정보가 없다면 제작자 서버와 동일한 것으로 처리한다. 수수료를 골드 단위로 소수점 4자리까지 기록한다.

## 프로젝트의 실행 방법

1. .env 파일로 (기본)
python wow_asset_tracker.py

2. 직접 지정
python wow_asset_tracker.py --lua-path "/path/to/TradeSkillMaster.lua" --output-path "./output"
