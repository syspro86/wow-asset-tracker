"""
WOW Asset Tracker
TradeSkillMaster Addon 설정 파일에서 WOW 자산 정보를 추출하여 일별 JSON 파일로 저장합니다.

목표:
  1. 일별 총 골드 정보를 캐릭터별/warbank별로 구분하여 저장한다.
     - 접속 기록이 없는 날은 직전 보유량을 이월(forward-fill)한다.
     - 저장 경로: $OUTPUT_PATH/gold/YYYY/MM/DD.json
  2. 전문기술 주문제작 내역을 추출하여 저장한다.
     - 날짜별: $OUTPUT_PATH/crafting/YYYY/MM/DD.json (주문제작 기록 일자 기준)
     - 요청자별: $OUTPUT_PATH/crafting/서버명/캐릭명.json

입력:
  --lua-path  또는  .env 의 LUA_PATH   : TradeSkillMaster.lua 파일 경로
  --output-path  또는  .env 의 OUTPUT_PATH : 출력 디렉토리 경로 (기본값: ./output)
"""

import re
import json
import argparse
import os
from datetime import date, datetime, timezone
from dotenv import load_dotenv

load_dotenv()  # .env 파일 로드


# ──────────────────────────────────────────────────────────────────────────────
# Lua 파일 파싱
# ──────────────────────────────────────────────────────────────────────────────

def parse_lua_file(path: str) -> dict:
    """TradeSkillMaster.lua 파일을 읽어 key-value 쌍의 딕셔너리로 반환합니다."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Lua 파일을 찾을 수 없습니다: {path}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 최상위 테이블 시작 라인 제거: "TradeSkillMasterDB = {"
    # 이후 최상위 key = value 쌍을 정규식으로 추출
    # 형식: ["<key>"] = <value>,
    #   value 는 숫자, 문자열 (큰따옴표), 또는 중첩 테이블 { ... }

    data = {}

    # 숫자 값 추출
    for m in re.finditer(r'^\["(.+?)"\] = (-?\d+),\s*$', content, re.MULTILINE):
        data[m.group(1)] = int(m.group(2))

    # 문자열 값 추출: ["key"] = "value",
    # value 내에 큰따옴표는 없고 이스케이프된 \n 이 있을 수 있음 → [^"]* 로 매칭
    for m in re.finditer(r'^\["(.+?)"\] = "([^"]*)",\s*$', content, re.MULTILINE):
        data[m.group(1)] = m.group(2)

    return data


# ──────────────────────────────────────────────────────────────────────────────
# 자산 추출
# ──────────────────────────────────────────────────────────────────────────────

def copper_to_gold(copper: int) -> float:
    """copper 단위를 골드 단위로 변환합니다."""
    return copper / 10000


def extract_assets(raw: dict) -> dict:
    """
    파싱된 Lua 딕셔너리에서 자산 정보를 추출합니다.

    반환 구조:
    {
        "extracted_at": "ISO-8601 timestamp",
        "characters": {
            "<name> - <faction> - <realm>": {
                "money_copper": int,
                "money_gold": float
            },
            ...
        },
        "warbank": {
            "money_copper": int,
            "money_gold": float
        },
        "total_copper": int,
        "total_gold": float
    }
    """
    assets = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "characters": {},
        "warbank": {},
        "total_copper": 0,
        "total_gold": 0.0,
    }

    # 캐릭터별 골드: 키 형식 → s@<char> - <faction> - <realm>@internalData@money
    char_money_pattern = re.compile(
        r"^s@(.+?)@internalData@money$"
    )

    for key, value in raw.items():
        m = char_money_pattern.match(key)
        if m and isinstance(value, int):
            char_name = m.group(1)
            assets["characters"][char_name] = {
                "money_copper": value,
                "money_gold": round(copper_to_gold(value), 4),
            }

    # 전쟁금고 (Warbank): 키 형식 → g@ @internalData@warbankMoney
    warbank_key = "g@ @internalData@warbankMoney"
    if warbank_key in raw and isinstance(raw[warbank_key], int):
        wb_copper = raw[warbank_key]
        assets["warbank"] = {
            "money_copper": wb_copper,
            "money_gold": round(copper_to_gold(wb_copper), 4),
        }

    # 총합 계산
    total_copper = sum(c["money_copper"] for c in assets["characters"].values())
    total_copper += assets.get("warbank", {}).get("money_copper", 0)
    assets["total_copper"] = total_copper
    assets["total_gold"] = round(copper_to_gold(total_copper), 4)

    return assets


# ──────────────────────────────────────────────────────────────────────────────
# 일별 골드 이력 추출 (goldLog / warbankGoldLog)
# ──────────────────────────────────────────────────────────────────────────────

def parse_gold_log(log_str: str) -> list[tuple[str, int]]:
    """
    goldLog 문자열("minute,copper\n...")을 파싱하여 (date_str, copper) 리스트로 반환합니다.
    minute = Unix 타임스탬프 // 60
    date_str = 'YYYY-MM-DD' (UTC)
    """
    # Lua 파일에서 개행 문자가 리터럴 \n 으로 저장되어 있으므로 변환
    log_str = log_str.replace("\\n", "\n")
    lines = log_str.strip().split("\n")
    if not lines or lines[0].strip() != "minute,copper":
        return []

    result = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        try:
            minute = int(parts[0])
            copper = int(parts[1])
        except ValueError:
            continue
        ts = minute * 60
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        result.append((date_str, copper))
    return result


def extract_daily_gold_history(raw: dict) -> dict:
    """
    설정 파일 내 모든 goldLog / warbankGoldLog 를 파싱하여
    일별 총 골드 이력을 반환합니다.

    접속 기록이 없는 날은 가장 최근 기록값을 이월(forward-fill)하므로
    모든 날짜에서 전체 캐릭터 + 전쟁금고 합산이 정확하게 계산됩니다.

    반환 구조:
    {
        "YYYY-MM-DD": {
            "characters_copper": int,
            "characters_gold": float,
            "warbank_copper": int,
            "warbank_gold": float,
            "total_copper": int,
            "total_gold": float
        },
        ...
    }
    """
    # 소스별 (날짜 → copper) 시계열 수집
    # source_key: "char:<name>" or "warbank"
    # source_timeline[source_key] = sorted list of (date_str, copper)
    source_timeline: dict[str, list[tuple[str, int]]] = {}

    char_log_pattern = re.compile(r"^s@(.+?)@internalData@goldLog$")

    for key, value in raw.items():
        if not isinstance(value, str):
            continue

        source = None
        if char_log_pattern.match(key):
            source = "char:" + char_log_pattern.match(key).group(1)
        elif key == "g@ @internalData@warbankGoldLog":
            source = "warbank"

        if source is None:
            continue

        entries = parse_gold_log(value)
        if not entries:
            continue

        if source not in source_timeline:
            source_timeline[source] = {}

        # 같은 날짜에 여러 기록이 있으면 마지막 값(append 순서)으로 덮어씀
        for date_str, copper in entries:
            source_timeline[source][date_str] = copper

    # 각 소스의 날짜 맵을 정렬된 리스트로 변환
    source_sorted: dict[str, list[tuple[str, int]]] = {
        src: sorted(date_map.items())
        for src, date_map in source_timeline.items()
    }

    # 전체 날짜 범위 산출
    all_dates: list[str] = sorted(
        {d for timeline in source_sorted.values() for d, _ in timeline}
    )
    if not all_dates:
        return {}

    # forward-fill: 날짜별로 각 소스의 "해당 날 이전 마지막 기록값" 계산
    history: dict[str, dict] = {}
    # 소스별 인덱스 포인터
    pointers: dict[str, int] = {src: 0 for src in source_sorted}
    # 소스별 현재(이월) 값
    current_vals: dict[str, int] = {src: 0 for src in source_sorted}

    for date_str in all_dates:
        # 각 소스에서 이 날짜까지 기록된 최신 값으로 갱신
        for src, timeline in source_sorted.items():
            idx = pointers[src]
            while idx < len(timeline) and timeline[idx][0] <= date_str:
                current_vals[src] = timeline[idx][1]
                idx += 1
            pointers[src] = idx

        char_copper = sum(
            v for k, v in current_vals.items() if k.startswith("char:")
        )
        wb_copper = current_vals.get("warbank", 0)
        total_copper = char_copper + wb_copper

        # 캐릭터별 상세 (정수 골드만 저장, 실버/코퍼 미만 제외)
        # 키: "CharName - Faction - ServerName" → "캐릭명-서버명"
        def _char_key(tsm_key: str) -> str:
            parts = tsm_key.split(" - ")
            if len(parts) == 3:
                return f"{parts[0]}-{parts[2]}"
            return tsm_key

        characters = {
            _char_key(k[len("char:"):]) : int(copper_to_gold(v))
            for k, v in current_vals.items()
            if k.startswith("char:")
        }


        history[date_str] = {
            "characters_gold": int(copper_to_gold(char_copper)),
            "warbank_gold": int(copper_to_gold(wb_copper)),
            "total_gold": int(copper_to_gold(total_copper)),
            "characters": characters,
            "warbank": int(copper_to_gold(wb_copper)),
        }

    return history



def save_gold_history(history: dict, output_dir: str) -> list[str]:
    """
    일별 골드 이력을 output_dir/gold/YYYY/MM/DD.json 파일로 저장합니다.
    저장된 파일 경로 리스트를 반환합니다.
    """
    saved = []
    for date_str, data in history.items():
        # date_str: "YYYY-MM-DD"
        yyyy, mm, dd = date_str.split("-")
        day_dir = os.path.join(output_dir, "gold", yyyy, mm)
        os.makedirs(day_dir, exist_ok=True)
        path = os.path.join(day_dir, f"{dd}.json")
        payload = {"date": date_str, **data}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        saved.append(path)
    return saved


def print_gold_history(history: dict, n: int = 10) -> None:
    """최근 n일의 일별 골드 이력을 콘솔에 출력합니다."""
    print("\n[일별 총 골드 이력 (최근 {} 일)]".format(n))
    print(f"  {'날짜':<12} {'캐릭터 합계':>16} {'전쟁금고':>16} {'총합':>16}")
    print("  " + "-" * 64)
    recent = list(history.items())[-n:]
    prev_total = None
    for date_str, data in recent:
        diff_str = ""
        if prev_total is not None:
            d = data["total_gold"] - prev_total
            sign = "+" if d >= 0 else ""
            diff_str = f" ({sign}{d:,.0f}G)"
        print(
            f"  {date_str:<12}"
            f" {data['characters_gold']:>14,.0f} G"
            f" {data['warbank_gold']:>14,.0f} G"
            f" {data['total_gold']:>14,.0f} G{diff_str}"
        )
        prev_total = data["total_gold"]



# ──────────────────────────────────────────────────────────────────────────────
# 주문제작 이력 추출 (csvIncome)
# ──────────────────────────────────────────────────────────────────────────────


def parse_csv_income(csv_str: str) -> list[dict]:
    """
    csvIncome 문자열을 파싱하여 Crafting Order 항목 리스트를 반환합니다.
    형식: type,amount,otherPlayer,player,time
    """
    csv_str = csv_str.replace("\\n", "\n")
    lines = csv_str.strip().split("\n")
    if not lines or lines[0].strip() != "type,amount,otherPlayer,player,time":
        return []

    records = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) != 5:
            continue
        rec_type, amount_str, other_player, player, time_str = parts
        if rec_type != "Crafting Order":
            continue
        try:
            amount = int(amount_str)
            ts = int(time_str)
        except ValueError:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        records.append({
            "date": dt.strftime("%Y-%m-%d"),
            "date_compact": dt.strftime("%Y%m%d"),
            "datetime": dt.isoformat(),
            "requester": other_player,
            "crafter": player,
            "amount_copper": amount,
            "amount_gold": round(copper_to_gold(amount), 4),
        })
    return records


def extract_crafting_orders(raw: dict) -> list[dict]:
    """
    모든 csvIncome 키에서 Crafting Order 레코드를 수집하여 날짜 순으로 정렬합니다.
    키 패턴: r@<서버>@internalData@csvIncome → 서버명을 crafter_server로 기록
    """
    pattern = re.compile(r"^r@(.+?)@internalData@csvIncome$")
    seen = set()
    records = []

    for key, value in raw.items():
        m = pattern.match(key)
        if not m:
            continue
        if not isinstance(value, str):
            continue
        crafter_server = m.group(1).strip()
        for rec in parse_csv_income(value):
            uid = (rec["requester"], rec["crafter"], rec["datetime"])
            if uid in seen:
                continue
            seen.add(uid)
            rec["crafter_server"] = crafter_server
            records.append(rec)

    records.sort(key=lambda r: r["datetime"])
    return records


def save_crafting_by_date(records: list[dict], output_dir: str) -> list[str]:
    """
    주문제작 날짜별로 output_dir/crafting/YYYY/MM/DD_crafting.json 저장.
    저장된 파일 경로 리스트를 반환합니다.
    """
    by_date: dict[str, list[dict]] = {}
    for rec in records:
        by_date.setdefault(rec["date_compact"], []).append(rec)

    saved = []
    for date_compact, recs in sorted(by_date.items()):
        yyyy, mm, dd = date_compact[:4], date_compact[4:6], date_compact[6:8]
        day_dir = os.path.join(output_dir, "crafting", yyyy, mm)
        os.makedirs(day_dir, exist_ok=True)
        path = os.path.join(day_dir, f"{dd}.json")
        total_copper = sum(r["amount_copper"] for r in recs)
        payload = {
            "date": recs[0]["date"],
            "total_orders": len(recs),
            "total_copper": total_copper,
            "total_gold": round(copper_to_gold(total_copper), 4),
            "orders": recs,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        saved.append(path)
    return saved


def _parse_requester(requester: str) -> tuple[str, str]:
    """
    요청자 문자열에서 (서버명, 캐릭명)을 분리합니다.
    형식: '캐릭명-서버명' 또는 '캐릭명' (서버 없음 → '_unknown')
    """
    if "-" in requester:
        char, server = requester.rsplit("-", 1)
        return server.strip(), char.strip()
    return "_unknown", requester.strip()


def _safe_name(name: str) -> str:
    """파일/디렉토리명에 사용할 수 없는 문자를 제거합니다."""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def save_crafting_by_requester(records: list[dict], output_dir: str) -> list[str]:
    """
    주문제작 요청자별로 output_dir/crafting/서버명/캐릭명.json 저장.
    - 요청자 서버 정보가 없으면 첫 번째 제작자 서버를 사용
    - 각 주문에 천로제작 아이템(수수료), 제작자 캐릭명, 서버명 포함
    """
    crafting_dir = os.path.join(output_dir, "crafting")

    by_requester: dict[str, list[dict]] = {}
    for rec in records:
        by_requester.setdefault(rec["requester"], []).append(rec)

    saved = []
    for requester, recs in sorted(by_requester.items()):
        server, char = _parse_requester(requester)
        # 요청자 서버 미확인 시 첫 번째 제작자 서버를 폴백으로 사용
        if server == "_unknown":
            server = recs[0].get("crafter_server", "_unknown")

        server_dir = os.path.join(crafting_dir, _safe_name(server))
        os.makedirs(server_dir, exist_ok=True)
        path = os.path.join(server_dir, f"{_safe_name(char)}.json")

        total_copper = sum(r["amount_copper"] for r in recs)
        payload = {
            "requester": requester,
            "server": server,
            "character": char,
            "total_orders": len(recs),
            "total_copper": total_copper,
            "total_gold": round(copper_to_gold(total_copper), 4),
            "orders": [
                {
                    "date": r["date"],
                    "datetime": r["datetime"],
                    "crafter": r["crafter"],
                    "crafter_server": r.get("crafter_server", ""),
                    "amount_copper": r["amount_copper"],
                    "amount_gold": r["amount_gold"],
                }
                for r in recs
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        saved.append(path)
    return saved


def print_crafting_summary(records: list[dict], n: int = 10) -> None:
    """예시: 최근 n건 주문제작 건수/총수익 요약 출력."""
    if not records:
        print("\n[주문제작 이력] 데이터 없음")
        return

    total_gold = sum(r["amount_copper"] for r in records) / 10000
    print(f"\n[주문제작 이력 요약] 총 {len(records)}건 / {total_gold:,.0f} G")

    # 요청자별 통계
    by_req: dict[str, dict] = {}
    for rec in records:
        req = rec["requester"]
        if req not in by_req:
            by_req[req] = {"count": 0, "copper": 0}
        by_req[req]["count"] += 1
        by_req[req]["copper"] += rec["amount_copper"]

    print(f"\n[요청자 TOP {n}]")
    print(f"  {'\uc694\uccad\uc790':<30} {'\uac74\uc218':>6} {'\uc218\uc775':>16}")
    print("  " + "-" * 56)
    top = sorted(by_req.items(), key=lambda x: -x[1]["copper"])[:n]
    for req, stat in top:
        print(
            f"  {req:<30} {stat['count']:>6}건"
            f" {copper_to_gold(stat['copper']):>14,.0f} G"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────────

def print_summary(assets: dict, diff: dict | None = None) -> None:
    """콘솔에 자산 요약을 출력합니다."""
    print("\n=== WOW Asset Tracker ===")
    print(f"추출 시각: {assets['extracted_at']}")
    print(f"\n[총 자산] {assets['total_gold']:,.4f} G  ({assets['total_copper']:,} copper)")

    if diff:
        sign = "+" if diff["total_diff_gold"] >= 0 else ""
        print(f"  ↳ 전일 대비: {sign}{diff['total_diff_gold']:,.4f} G")

    print("\n[캐릭터별 골드]")
    for char, data in sorted(
        assets["characters"].items(),
        key=lambda x: x[1]["money_copper"],
        reverse=True,
    ):
        print(f"  {char:<50} {data['money_gold']:>14,.4f} G", end="")
        if diff and char in diff["characters"]:
            d = diff["characters"][char]["diff_gold"]
            sign = "+" if d >= 0 else ""
            print(f"  ({sign}{d:,.4f} G)", end="")
        print()

    if assets.get("warbank"):
        wb = assets["warbank"]
        print(f"\n[전쟁금고] {wb['money_gold']:,.4f} G", end="")
        if diff and diff.get("warbank"):
            d = diff["warbank"]["diff_gold"]
            sign = "+" if d >= 0 else ""
            print(f"  ({sign}{d:,.4f} G)", end="")
        print()


# ──────────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WOW TradeSkillMaster 자산 추출기",
    )
    parser.add_argument(
        "--lua-path",
        default=os.getenv("LUA_PATH"),
        help="TradeSkillMaster.lua 파일 경로 (.env의 LUA_PATH 또는 이 인수로 지정)",
    )
    parser.add_argument(
        "--output-path",
        default=os.getenv("OUTPUT_PATH", "./output"),
        help="출력 디렉토리 경로 (.env의 OUTPUT_PATH 또는 이 인수로 지정)",
    )
    args = parser.parse_args()
    if not args.lua_path:
        parser.error("LUA_PATH를 --lua-path 인수나 .env 파일로 지정해야 합니다.")
    return args


def main() -> None:
    args = parse_args()

    print(f"Lua 파일 읽는 중: {args.lua_path}")
    raw = parse_lua_file(args.lua_path)

    # 일별 골드 이력 추출 및 저장
    print("일별 골드 이력 추출 중...")
    history = extract_daily_gold_history(raw)
    gold_files = save_gold_history(history, args.output_path)
    print(f"골드 이력 저장 완료: {len(gold_files)}개 파일 (output/gold/)")

    # 주문제작 이력 추출 및 저장
    print("주문제작 이력 추출 중...")
    crafting_records = extract_crafting_orders(raw)
    date_files = save_crafting_by_date(crafting_records, args.output_path)
    req_files = save_crafting_by_requester(crafting_records, args.output_path)
    print(f"날짜별 저장 완료: {len(date_files)}개 파일")
    print(f"요청자별 저장 완료: {len(req_files)}개 파일 (output/crafting/)")

    # 요약 출력
    print_gold_history(history)
    print_crafting_summary(crafting_records)


if __name__ == "__main__":
    main()
