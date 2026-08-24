import json
import random
import time
import urllib.parse
import urllib.request
import re

from datetime import datetime, timedelta

import streamlit as st
from streamlit_local_storage import LocalStorage
from streamlit_autorefresh import st_autorefresh
st_autorefresh(interval=5 * 60 * 1000, key="vocab_refresh")


# ============================================================
# 1. CẤU HÌNH APP
# ============================================================

st.set_page_config(
    page_title="MochiVocab",
    page_icon="🍌",
    layout="centered"
)

local_storage = LocalStorage()


# ============================================================
# 2. CẤU HÌNH CÁC MỐC GOLDEN TIME
# ============================================================
#
# Cấp 0:
#   0h
#
# Cấp 1:
#   1h -> 4h -> 12h -> 24h
#
# Cấp 2:
#   25h -> 28h -> 36h -> 48h
#
# Cấp 3:
#   49h -> 52h -> 60h -> 72h
#
# Cấp 4:
#   73h -> 76h -> 84h -> 96h
#
# Cấp 5:
#   97h -> 100h -> 108h -> 120h
#
# Mỗi cấp có 4 móc.
# slot = 0, 1, 2, 3
#
# Khi hoàn thành slot 3:
#   cấp hiện tại + 1
#   slot = 0
#
# Khi sai:
#   lùi 1 slot
#   nhưng không được rơi xuống cấp 0
#
# Ví dụ:
#   Cấp 2 móc 0 -> sai -> vẫn Cấp 2 móc 0
#   Cấp 2 móc 2 -> sai -> Cấp 2 móc 1
#

GOLDEN_HOURS = {
    0: [0],
    1: [1, 4, 12, 24],
    2: [25, 28, 36, 48],
    3: [49, 52, 60, 72],
    4: [73, 76, 84, 96],
    5: [97, 100, 108, 120],
}

MAX_LEVEL = 5
SLOTS_PER_LEVEL = 4

# Nếu quá hạn thì cứ mỗi lần kiểm tra sẽ xử lý hạ móc.
# Không bao giờ hạ từ cấp 1 móc 0 xuống cấp 0.
OVERDUE_DROP_ENABLED = True

# 5 phút kiểm tra một lần.
AUTO_REFRESH_MS = 5 * 60 * 1000


# ============================================================
# 3. SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "deck": [],
    "data_loaded": False,
    "review_item": None,
    "q_type": None,
    "q_data": {},
    "review_start_time": 0,
    "active_tab": "⏰ Ôn Tập",
    "temp_word": None,
    "review_started": False,
    "notification_permission_requested": False,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        if isinstance(value, list):
            st.session_state[key] = []
        elif isinstance(value, dict):
            st.session_state[key] = {}
        else:
            st.session_state[key] = value


# ============================================================
# 4. FORMAT THỜI GIAN
# ============================================================

def format_interval(minutes):
    minutes = int(max(0, minutes))

    if minutes < 60:
        return f"{minutes} phút"

    if minutes < 1440:
        hours = minutes / 60

        if hours.is_integer():
            return f"{int(hours)} giờ"

        return f"{hours:.1f} giờ"

    days = minutes / 1440

    if days.is_integer():
        return f"{int(days)} ngày"

    return f"{days:.1f} ngày"


def format_remaining(seconds):
    seconds = int(max(0, seconds))

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days} ngày {hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# ============================================================
# 5. GOLDEN TIME
# ============================================================

def get_level_slots(level):
    """
    Trả về danh sách 4 mốc của cấp.
    """

    level = int(level)

    if level <= 0:
        return [0, 0, 0, 0]

    return GOLDEN_HOURS.get(
        level,
        GOLDEN_HOURS[MAX_LEVEL]
    )


def get_slot_hours(level, slot):
    """
    Lấy số giờ tương ứng với cấp + móc.
    """

    level = max(1, min(int(level), MAX_LEVEL))
    slot = max(0, min(int(slot), SLOTS_PER_LEVEL - 1))

    return GOLDEN_HOURS[level][slot]


def get_slot_minutes(level, slot):
    return get_slot_hours(level, slot) * 60


def get_current_golden_label(item):
    level = int(item.get("level", 0))
    slot = int(item.get("slot", 0))

    if level == 0:
        return "0h — Từ mới"

    hours = get_slot_hours(level, slot)

    return f"{hours}h — Cấp {level}, móc {slot + 1}/4"


def get_level_name(level):
    names = {
        0: "🆕 Từ mới",
        1: "🥉 Cấp 1",
        2: "🥈 Cấp 2",
        3: "🥇 Cấp 3",
        4: "💎 Cấp 4",
        5: "🏆 Cấp 5",
    }

    return names.get(level, "🆕 Từ mới")


def get_progress_text(item):
    level = int(item.get("level", 0))
    slot = int(item.get("slot", 0))

    if level == 0:
        return "0h"

    hours = get_slot_hours(level, slot)

    return f"{hours}h — móc {slot + 1}/4"


# ============================================================
# 6. TĂNG MÓC KHI TRẢ LỜI ĐÚNG
# ============================================================

def advance_after_correct(item):
    """
    Đúng:
      Cấp 1 móc 1 -> móc 2
      Cấp 1 móc 2 -> móc 3
      Cấp 1 móc 3 -> móc 4
      Cấp 1 móc 4 -> Cấp 2 móc 1

    Cấp 0:
      lần đầu trả lời đúng -> Cấp 1 móc 1
    """

    level = int(item.get("level", 0))
    slot = int(item.get("slot", 0))

    # --------------------------------------------------------
    # TỪ MỚI
    # --------------------------------------------------------

    if level <= 0:
        return 1, 0

    # --------------------------------------------------------
    # CHƯA HẾT 4 MÓC
    # --------------------------------------------------------

    if slot < SLOTS_PER_LEVEL - 1:
        return level, slot + 1

    # --------------------------------------------------------
    # ĐÃ ĐỦ 4 MÓC
    # --------------------------------------------------------

    if level < MAX_LEVEL:
        return level + 1, 0

    # --------------------------------------------------------
    # ĐÃ CẤP 5 MÓC 4
    # Giữ nguyên cấp 5 móc 4.
    # --------------------------------------------------------

    return MAX_LEVEL, SLOTS_PER_LEVEL - 1


# ============================================================
# 7. LÙI MÓC KHI SAI
# ============================================================

def move_back_after_wrong(item):
    """
    Sai:
      Cấp 3 móc 4 -> Cấp 3 móc 3
      Cấp 3 móc 2 -> Cấp 3 móc 1
      Cấp 3 móc 1 -> vẫn Cấp 3 móc 1

    KHÔNG BAO GIỜ:
      Cấp 1 móc 1 -> Cấp 0

    Cấp 0:
      vẫn Cấp 0.
    """

    level = int(item.get("level", 0))
    slot = int(item.get("slot", 0))

    # Từ mới vẫn là từ mới.
    if level <= 0:
        return 0, 0

    # Không cho cấp 1 rơi về cấp 0.
    if level == 1 and slot == 0:
        return 1, 0

    # Lùi trong cùng cấp.
    if slot > 0:
        return level, slot - 1

    # Trường hợp đang ở móc đầu của cấp > 1.
    # Sai thì vẫn giữ móc đầu của cấp đó.
    #
    # Ví dụ:
    # Cấp 2 móc 1 -> sai -> vẫn Cấp 2 móc 1.
    return level, 0


# ============================================================
# 8. HẠ MÓC KHI QUÁ HẠN
# ============================================================

def apply_overdue_penalty(item, now=None):
    """
    Nếu từ đã quá hạn mà người dùng chưa ôn,
    hạ 1 móc.

    Quy tắc:
      Cấp 1 móc 1 -> vẫn Cấp 1 móc 1
      Cấp 1 móc 2 -> Cấp 1 móc 1
      Cấp 1 móc 3 -> Cấp 1 móc 2
      Cấp 2 móc 1 -> vẫn Cấp 2 móc 1

    Không hạ liên tục trong mỗi lần rerun.
    Mỗi item chỉ bị phạt một lần cho một lần đến hạn.
    """

    if now is None:
        now = datetime.now()

    if not OVERDUE_DROP_ENABLED:
        return False

    changed = False

    level = int(item.get("level", 0))
    slot = int(item.get("slot", 0))

    next_review = item.get("next_review")

    if not isinstance(next_review, datetime):
        try:
            next_review = datetime.fromisoformat(str(next_review))
            item["next_review"] = next_review
        except Exception:
            return False

    if next_review > now:
        return False

    # Không xử lý phạt lại liên tục nếu đã xử lý quá hạn.
    overdue_handled = item.get("overdue_handled", False)

    if overdue_handled:
        return False

    # Từ mới cấp 0 không áp dụng phạt.
    if level == 0:
        item["overdue_handled"] = True
        return False

    new_level, new_slot = move_back_after_wrong(item)

    if new_level != level or new_slot != slot:
        item["level"] = new_level
        item["slot"] = new_slot
        changed = True

    item["overdue_handled"] = True

    # Sau khi hạ móc, tạo lại thời điểm ôn.
    if new_level > 0:
        interval_minutes = get_slot_minutes(new_level, new_slot)
        item["interval"] = interval_minutes

        # Khi phát hiện quá hạn, cho người dùng ôn ngay.
        item["next_review"] = now

    return changed


def process_overdue_items():
    """
    Kiểm tra toàn bộ deck.
    """

    now = datetime.now()
    changed = False

    for item in st.session_state.deck:
        try:
            if apply_overdue_penalty(item, now):
                changed = True
        except Exception:
            continue

    if changed:
        save_deck()


# ============================================================
# 9. LOAD LOCAL STORAGE
# ============================================================

def normalize_item(item):
    """
    Chuẩn hóa dữ liệu cũ.
    """

    if not isinstance(item, dict):
        return None

    word = str(item.get("word", "")).strip()

    if not word:
        return None

    # --------------------------------------------------------
    # next_review
    # --------------------------------------------------------

    next_review = item.get("next_review")

    if isinstance(next_review, str):
        try:
            next_review = datetime.fromisoformat(next_review)
        except Exception:
            next_review = datetime.now()

    if not isinstance(next_review, datetime):
        next_review = datetime.now()

    # --------------------------------------------------------
    # level
    # --------------------------------------------------------

    try:
        level = int(item.get("level", 0))
    except Exception:
        level = 0

    level = max(0, min(level, MAX_LEVEL))

    # --------------------------------------------------------
    # slot
    # --------------------------------------------------------

    try:
        slot = int(item.get("slot", 0))
    except Exception:
        slot = 0

    slot = max(0, min(slot, SLOTS_PER_LEVEL - 1))

    # --------------------------------------------------------
    # Cấp 0 luôn slot 0
    # --------------------------------------------------------

    if level == 0:
        slot = 0

    # --------------------------------------------------------
    # interval
    # --------------------------------------------------------

    try:
        interval = float(item.get("interval", 0))
    except Exception:
        interval = 0

    if level > 0:
        correct_interval = get_slot_minutes(level, slot)

        if interval <= 0:
            interval = correct_interval

    else:
        interval = 0

    # --------------------------------------------------------
    # counters
    # --------------------------------------------------------

    try:
        review_count = int(item.get("review_count", 0))
    except Exception:
        review_count = 0

    try:
        correct_count = int(item.get("correct_count", 0))
    except Exception:
        correct_count = 0

    try:
        wrong_count = int(item.get("wrong_count", 0))
    except Exception:
        wrong_count = 0

    # --------------------------------------------------------
    # Return
    # --------------------------------------------------------

    return {
        "id": int(item.get("id", 0)),
        "word": word,
        "phonetic": str(item.get("phonetic", "")),
        "meaning": str(item.get("meaning", "")).strip(),
        "example": str(item.get("example", "")).strip(),

        "level": level,
        "slot": slot,
        "interval": interval,

        "review_count": review_count,
        "correct_count": correct_count,
        "wrong_count": wrong_count,

        "last_response_time": item.get("last_response_time"),
        "last_result": item.get("last_result"),

        "next_review": next_review,

        "overdue_handled": bool(
            item.get("overdue_handled", False)
        ),
    }


def load_deck():
    try:
        saved_data = local_storage.getItem("mochi_deck_data")

        if not saved_data:
            return []

        items = json.loads(saved_data)

        if not isinstance(items, list):
            return []

        cleaned = []

        for item in items:
            normalized = normalize_item(item)

            if normalized:
                cleaned.append(normalized)

        return cleaned

    except Exception:
        return []


if not st.session_state.data_loaded:
    st.session_state.deck = load_deck()
    st.session_state.data_loaded = True


# ============================================================
# 10. SAVE LOCAL STORAGE
# ============================================================

def save_deck():
    serializable_deck = []

    for item in st.session_state.deck:
        copy_item = item.copy()

        if isinstance(copy_item.get("next_review"), datetime):
            copy_item["next_review"] = copy_item[
                "next_review"
            ].isoformat()

        serializable_deck.append(copy_item)

    local_storage.setItem(
        "mochi_deck_data",
        json.dumps(
            serializable_deck,
            ensure_ascii=False
        )
    )


# ============================================================
# 11. KIỂM TRA QUÁ HẠN
# ============================================================

process_overdue_items()


# ============================================================
# 12. AUTO REFRESH 5 PHÚT
# ============================================================
#
# Browser sẽ yêu cầu Streamlit rerun mỗi 5 phút.
#
# Đây là cơ chế phù hợp với Streamlit để kiểm tra dữ liệu
# định kỳ mà không dùng while True + sleep.
#

try:
    st_autorefresh(
        interval=AUTO_REFRESH_MS,
        limit=None,
        key="mochi_auto_refresh"
    )
except Exception:
    pass


# ============================================================
# 13. BROWSER NOTIFICATION
# ============================================================

def render_notification_permission():
    notification_html = """
    <script>
    (function() {
        try {
            if (!("Notification" in window)) {
                return;
            }

            if (Notification.permission === "default") {
                // Không tự động gọi permission khi page vừa mở.
                // Nút bên dưới sẽ gọi requestPermission().
            }
        } catch (e) {
            console.log(e);
        }
    })();
    </script>
    """

    st.components.v1.html(
        notification_html,
        height=0
    )


def request_notification_permission():
    html = """
    <script>
    (function() {
        try {
            if ("Notification" in window) {
                Notification.requestPermission().then(function(permission) {
                    console.log("Notification permission:", permission);
                });
            } else {
                alert("Trình duyệt này không hỗ trợ thông báo.");
            }
        } catch (e) {
            console.log(e);
        }
    })();
    </script>
    """

    st.components.v1.html(
        html,
        height=0
    )


def send_browser_notification(words):
    if not words:
        return

    safe_words = json.dumps(
        words[:10],
        ensure_ascii=False
    )

    notification_html = f"""
    <script>
    (function() {{
        try {{
            if (!("Notification" in window)) {{
                return;
            }}

            if (Notification.permission !== "granted") {{
                return;
            }}

            var words = {safe_words};

            var body = "";

            if (words.length === 1) {{
                body = "Đã đến Thời Điểm Vàng của: " + words[0];
            }} else {{
                body = "Có " + words.length +
                       " từ đã đến Thời Điểm Vàng: " +
                       words.join(", ");
            }}

            new Notification(
                "🍌 MochiVocab",
                {{
                    body: body,
                    icon: "🍌",
                    tag: "mochivocab-review"
                }}
            );

        }} catch (e) {{
            console.log(e);
        }}
    }})();
    </script>
    """

    st.components.v1.html(
        notification_html,
        height=0
    )


render_notification_permission()


# ============================================================
# 14. TÌM TỪ ĐẾN GIỜ
# ============================================================

def get_due_items():
    now = datetime.now()

    return [
        item
        for item in st.session_state.deck
        if item.get("next_review", now) <= now
    ]


due_items_global = get_due_items()


# ============================================================
# 15. THÔNG BÁO TRONG APP
# ============================================================

if due_items_global:
    notification_words = [
        item["word"].upper()
        for item in due_items_global
    ]

    # Toast ở mỗi lần app rerun.
    # Vì auto-refresh 5 phút nên khi app đang mở,
    # thông báo sẽ được kiểm tra lại mỗi 5 phút.
    try:
        st.toast(
            f"⏰ Đã đến giờ ôn {len(notification_words)} từ!",
            icon="🍌"
        )
    except Exception:
        pass

    send_browser_notification(notification_words)


# ============================================================
# 16. PHÁT ÂM
# ============================================================

def play_audio_script(word):
    safe_word = (
        word
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", " ")
        .replace("\r", " ")
    )

    js_code = f"""
    <script>
    window.speechSynthesis.cancel();

    var msg = new SpeechSynthesisUtterance('{safe_word}');

    msg.lang = 'en-US';
    msg.rate = 0.9;

    window.speechSynthesis.speak(msg);
    </script>
    """

    st.components.v1.html(
        js_code,
        height=0
    )


# ============================================================
# 17. DỊCH ANH -> VIỆT
# ============================================================

def translate_single_text(text):
    """
    Dịch từ tiếng Anh sang tiếng Việt.

    Nếu Google Translate không trả được kết quả,
    sẽ thử thêm MyMemory.
    """

    if not text or not text.strip():
        return text

    text = text.strip()

    # --------------------------------------------------------
    # Google Translate
    # --------------------------------------------------------

    try:
        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
            "?client=gtx"
            "&sl=en"
            "&tl=vi"
            "&dt=t"
            f"&q={urllib.parse.quote(text)}"
        )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            translated = "".join(
                part[0]
                for part in data[0]
                if part and part[0]
            ).strip()

            if translated:
                return translated

    except Exception:
        pass

    # --------------------------------------------------------
    # MyMemory fallback
    # --------------------------------------------------------

    try:
        url = (
            "https://api.mymemory.translated.net/get"
            f"?q={urllib.parse.quote(text)}"
            "&langpair=en|vi"
        )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            translated = (
                data
                .get("responseData", {})
                .get("translatedText", "")
                .strip()
            )

            if translated:
                return translated

    except Exception:
        pass

    # Không dịch được thì trả về chuỗi gốc.
    return text


# ============================================================
# 18. DICTIONARY API
# ============================================================

def fetch_word_full_data_FAST(word):
    url = (
        "https://api.dictionaryapi.dev/"
        f"api/v2/entries/en/"
        f"{urllib.parse.quote(word)}"
    )

    meanings_raw = []
    examples = []

    phonetic = f"/{word}/"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            if isinstance(data, list) and data:

                first = data[0]

                phonetic = (
                    first.get("phonetic")
                    or phonetic
                )

                for meaning in first.get(
                    "meanings",
                    []
                ):

                    pos = meaning.get(
                        "partOfSpeech",
                        "từ"
                    )

                    for definition in meaning.get(
                        "definitions",
                        []
                    ):

                        definition_text = (
                            definition
                            .get("definition")
                        )

                        if definition_text:
                            meanings_raw.append({
                                "type": pos,
                                "en": definition_text
                            })

                        example_text = (
                            definition.get("example")
                        )

                        if example_text:
                            examples.append(
                                example_text
                            )

                        if len(meanings_raw) >= 3:
                            break

                    if len(meanings_raw) >= 3:
                        break

    except Exception:
        pass

    if not meanings_raw:
        return {
            "success": False
        }

    # --------------------------------------------------------
    # Dịch chính TỪ đang tra sang tiếng Việt
    # --------------------------------------------------------

    short_vn = translate_single_text(word)

    # --------------------------------------------------------
    # Nếu kết quả vẫn giống từ tiếng Anh,
    # thử dịch definition.
    # --------------------------------------------------------

    if (
        not short_vn
        or short_vn.strip().lower()
        == word.strip().lower()
    ):

        definition_vn = translate_single_text(
            meanings_raw[0]["en"]
        )

        if definition_vn:
            short_vn = definition_vn

    return {
        "success": True,
        "phonetic": phonetic,
        "short_vn": short_vn,
        "examples": examples,
        "definitions": meanings_raw
    }


def fetch_online_word_data(word):
    """
    Lấy example từ Dictionary API.
    """

    try:
        url = (
            "https://api.dictionaryapi.dev/"
            f"api/v2/entries/en/"
            f"{urllib.parse.quote(word)}"
        )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            if isinstance(data, list) and data:

                for meaning in data[0].get(
                    "meanings",
                    []
                ):

                    for definition in meaning.get(
                        "definitions",
                        []
                    ):

                        example = definition.get(
                            "example"
                        )

                        if example:
                            return example

    except Exception:
        pass

    return None


# ============================================================
# 19. ID
# ============================================================

def get_next_id():
    if not st.session_state.deck:
        return 1

    ids = []

    for item in st.session_state.deck:
        try:
            ids.append(
                int(item.get("id", 0))
            )
        except Exception:
            pass

    return max(ids, default=0) + 1


# ============================================================
# 20. TẠO CÂU HỎI
# ============================================================

def prepare_review_question(item):

    # --------------------------------------------------------
    # Bỏ AUDIO_CHOICE.
    #
    # 6 dạng còn lại:
    # 1. CHOICE_MEANING
    # 2. FILL_BLANK
    # 3. SPELLING
    # 4. CONTEXT_MATCH
    # 5. FLASHCARD_TRUE_FALSE
    # 6. MEANING_CHOICE
    # --------------------------------------------------------

    q_types = [
        "CHOICE_MEANING",
        "FILL_BLANK",
        "SPELLING",
        "CONTEXT_MATCH",
        "FLASHCARD_TRUE_FALSE",
        "MEANING_CHOICE",
    ]

    chosen_q = random.choice(q_types)

    st.session_state.review_item = item
    st.session_state.q_type = chosen_q
    st.session_state.review_start_time = time.time()
    st.session_state.q_data = {}

    word = item.get(
        "word",
        ""
    ).strip()

    meaning = item.get(
        "meaning",
        ""
    ).strip()

    example = item.get(
        "example",
        ""
    ).strip()

    # --------------------------------------------------------
    # Nếu không có example -> lấy online.
    # --------------------------------------------------------

    if not example:
        online_example = fetch_online_word_data(word)

        if online_example:
            example = online_example
            item["example"] = example
            save_deck()

        else:
            example = (
                f"It is important to understand {word}."
            )

    # --------------------------------------------------------
    # Danh sách distractors
    # --------------------------------------------------------

    deck_words = [
        x.get("word", "").strip()
        for x in st.session_state.deck
        if (
            x.get("word", "").strip()
            and x.get("word", "").strip().lower()
            != word.lower()
        )
    ]

    deck_meanings = [
        x.get("meaning", "").strip()
        for x in st.session_state.deck
        if (
            x.get("meaning", "").strip()
            and x.get("meaning", "").strip()
            != meaning
        )
    ]

    # ========================================================
    # 1. TỪ -> CHỌN NGHĨA
    # ========================================================

    if chosen_q == "CHOICE_MEANING":

        options = [meaning]

        if deck_meanings:
            distractors = random.sample(
                deck_meanings,
                min(len(deck_meanings), 3)
            )

            for d in distractors:
                if d not in options:
                    options.append(d)

        fallback_meanings = [
            "Sự phát triển",
            "Khả năng thích nghi",
            "Thành tựu",
            "Môi trường",
            "Kinh nghiệm",
            "Sự kiên cường",
            "Cải tiến",
            "Thành công",
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

        options = options[:4]

        random.shuffle(options)

        st.session_state.q_data = {
            "question": word,
            "options": options,
            "answer": meaning,
        }

    # ========================================================
    # 2. ĐIỀN VÀO CHỖ TRỐNG
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        # ----------------------------------------------------
        # Tìm từ trong câu không phân biệt hoa thường.
        # ----------------------------------------------------

        pattern = re.compile(
            re.escape(word),
            re.IGNORECASE
        )

        blank_sentence = pattern.sub(
            "_____",
            example
        )

        # ----------------------------------------------------
        # Nếu example không chứa từ:
        #
        # Không cố nhét từ vào giữa câu một cách vô nghĩa.
        # Thay vào đó dùng câu online nếu có.
        # ----------------------------------------------------

        if blank_sentence == example:

            online_example = fetch_online_word_data(
                word
            )

            if online_example:

                example = online_example

                item["example"] = example

                blank_sentence = pattern.sub(
                    "_____",
                    example
                )

                save_deck()

        # ----------------------------------------------------
        # Nếu vẫn không tìm thấy từ,
        # dùng câu mẫu có vị trí rõ ràng.
        # ----------------------------------------------------

        if blank_sentence == example:

            blank_sentence = (
                f"This sentence uses the word _____ "
                f"correctly."
            )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word,
            "word": word,
        }

    # ========================================================
    # 3. NGHĨA -> GÕ TỪ
    # ========================================================

    elif chosen_q == "SPELLING":

        st.session_state.q_data = {
            "question": meaning,
            "answer": word,
        }

    # ========================================================
    # 4. NGỮ CẢNH -> CHỌN NGHĨA
    # ========================================================

    elif chosen_q == "CONTEXT_MATCH":

        options = [meaning]

        if deck_meanings:

            distractors = random.sample(
                deck_meanings,
                min(len(deck_meanings), 3)
            )

            for d in distractors:

                if d not in options:
                    options.append(d)

        fallback_meanings = [
            "Sự phát triển",
            "Khả năng thích nghi",
            "Thành tựu",
            "Môi trường",
            "Kinh nghiệm",
            "Sự kiên cường",
            "Cải tiến",
            "Thành công",
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

        options = options[:4]

        random.shuffle(options)

        st.session_state.q_data = {
            "context": example,
            "word": word,
            "options": options,
            "answer": meaning,
        }

    # ========================================================
    # 5. FLASHCARD TRUE/FALSE
    # ========================================================

    elif chosen_q == "FLASHCARD_TRUE_FALSE":

        is_true = random.choice(
            [True, False]
        )

        if is_true or not deck_meanings:

            display_meaning = meaning
            answer = True

        else:

            display_meaning = random.choice(
                deck_meanings
            )

            answer = False

        st.session_state.q_data = {
            "word": word,
            "disp_meaning": display_meaning,
            "is_true": answer,
            "answer": answer,
        }

    # ========================================================
    # 6. NGHĨA -> CHỌN TỪ
    # ========================================================

    elif chosen_q == "MEANING_CHOICE":

        options = [word]

        if deck_words:

            sampled_words = random.sample(
                deck_words,
                min(len(deck_words), 3)
            )

            for w in sampled_words:

                if w.lower() not in [
                    x.lower()
                    for x in options
                ]:
                    options.append(w)

        fallback_words = [
            "resilience",
            "innovate",
            "experience",
            "development",
            "adaptation",
            "success",
            "environment",
        ]

        for fb in fallback_words:

            if len(options) >= 4:
                break

            if fb.lower() not in [
                x.lower()
                for x in options
            ]:
                options.append(fb)

        options = options[:4]

        random.shuffle(options)

        st.session_state.q_data = {
            "word": word,
            "question": meaning,
            "options": options,
            "answer": word,
        }


# ============================================================
# 21. XỬ LÝ CÂU TRẢ LỜI
# ============================================================

def process_answer(
    is_correct,
    correct_ans_text
):

    item = st.session_state.review_item

    if item is None:
        return

    response_time = max(
        0.1,
        time.time()
        - st.session_state.review_start_time
    )

    old_level = int(
        item.get("level", 0)
    )

    old_slot = int(
        item.get("slot", 0)
    )

    old_label = get_current_golden_label(
        item
    )

    # ========================================================
    # ĐÚNG
    # ========================================================

    if is_correct:

        new_level, new_slot = (
            advance_after_correct(item)
        )

        item["correct_count"] = (
            int(
                item.get(
                    "correct_count",
                    0
                )
            ) + 1
        )

        item["review_count"] = (
            int(
                item.get(
                    "review_count",
                    0
                )
            ) + 1
        )

        item["last_response_time"] = round(
            response_time,
            2
        )

        item["last_result"] = "correct"

        item["level"] = new_level
        item["slot"] = new_slot

        # Đã trả lời nên reset trạng thái overdue.
        item["overdue_handled"] = False

        # ----------------------------------------------------
        # Tính mốc tiếp theo
        # ----------------------------------------------------

        if new_level == 0:

            interval_minutes = 0
            item["interval"] = 0

            item["next_review"] = (
                datetime.now()
                + timedelta(minutes=5)
            )

        else:

            interval_minutes = (
                get_slot_minutes(
                    new_level,
                    new_slot
                )
            )

            item["interval"] = (
                interval_minutes
            )

            item["next_review"] = (
                datetime.now()
                + timedelta(
                    minutes=interval_minutes
                )
            )

        save_deck()

        # ----------------------------------------------------
        # UI kết quả
        # ----------------------------------------------------

        st.success(
            "✨ Chính xác!"
        )

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        st.info(
            f"📍 Mốc cũ: **{old_label}**"
        )

        new_label = get_current_golden_label(
            item
        )

        if new_level > old_level:

            st.success(
                f"📈 Đủ 4 móc! "
                f"Cấp **{old_level} → {new_level}**"
            )

        elif new_slot > old_slot:

            st.success(
                f"📈 Tiến lên móc "
                f"**{new_slot + 1}/4**"
            )

        else:

            st.success(
                "🏆 Bạn đang ở mốc cao nhất!"
            )

        st.info(
            f"⏰ Mốc tiếp theo: "
            f"**{new_label}**"
        )

        if (
            new_level == MAX_LEVEL
            and new_slot == SLOTS_PER_LEVEL - 1
        ):

            st.balloons()

            st.success(
                "🏆 Từ này đã đạt "
                "Cấp 5 — móc 4/4!"
            )

    # ========================================================
    # SAI
    # ========================================================

    else:

        new_level, new_slot = (
            move_back_after_wrong(item)
        )

        item["wrong_count"] = (
            int(
                item.get(
                    "wrong_count",
                    0
                )
            ) + 1
        )

        item["review_count"] = (
            int(
                item.get(
                    "review_count",
                    0
                )
            ) + 1
        )

        item["last_response_time"] = round(
            response_time,
            2
        )

        item["last_result"] = "wrong"

        item["level"] = new_level
        item["slot"] = new_slot

        # ----------------------------------------------------
        # Sai thì câu hỏi mới sẽ được tạo lại.
        #
        # next_review = now
        # để từ này tiếp tục xuất hiện.
        # ----------------------------------------------------

        item["overdue_handled"] = False

        if new_level == 0:

            item["interval"] = 0

            # Từ mới sai vẫn là từ mới,
            # có thể làm lại ngay.
            item["next_review"] = datetime.now()

        else:

            interval_minutes = (
                get_slot_minutes(
                    new_level,
                    new_slot
                )
            )

            item["interval"] = (
                interval_minutes
            )

            # Quan trọng:
            # sai -> tạo câu hỏi mới ngay.
            item["next_review"] = (
                datetime.now()
            )

        save_deck()

        st.error(
            "❌ Chưa chính xác."
        )

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        st.warning(
            f"Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        st.info(
            f"📍 Mốc cũ: **{old_label}**"
        )

        new_label = get_current_golden_label(
            item
        )

        if (
            old_level == 1
            and old_slot == 0
            and new_level == 1
            and new_slot == 0
        ):

            st.warning(
                "🔒 Đây là móc đầu tiên của "
                "Cấp 1 nên không thể rơi về Cấp 0."
            )

        else:

            st.warning(
                f"📉 Lùi về: **{new_label}**"
            )

        st.info(
            "🔄 Đang tạo câu hỏi mới cho từ này..."
        )

    # ========================================================
    # XÓA CÂU HỎI CŨ
    # ========================================================

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    # Không sleep lâu vì sẽ làm app chậm.
    time.sleep(0.4)

    st.rerun()


# ============================================================
# 22. RESET TOÀN BỘ VỀ CẤP 0
# ============================================================

def reset_all_to_level_zero():

    now = datetime.now()

    for item in st.session_state.deck:

        item["level"] = 0
        item["slot"] = 0
        item["interval"] = 0

        item["review_count"] = 0
        item["correct_count"] = 0
        item["wrong_count"] = 0

        item["last_response_time"] = None
        item["last_result"] = None

        item["next_review"] = now

        item["overdue_handled"] = False

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}
    st.session_state.review_started = False
    st.session_state.temp_word = None

    save_deck()


# ============================================================
# 23. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Dynamic Golden Time — 4 móc mỗi cấp"
)

now = datetime.now()

due_count = sum(
    1
    for x in st.session_state.deck
    if x.get("next_review", now) <= now
)

tab_options = [
    "⏰ Ôn Tập",
    "🔍 Tra Từ Mới",
    "📋 Sổ Tay",
]

tab_labels = {
    "⏰ Ôn Tập": (
        f"⏰ Ôn Tập ({due_count})"
    ),

    "🔍 Tra Từ Mới":
        "🔍 Tra Từ Mới",

    "📋 Sổ Tay": (
        f"📋 Sổ Tay "
        f"({len(st.session_state.deck)})"
    ),
}

selected_tab = st.radio(
    "Navigation",
    options=tab_options,
    format_func=lambda x: tab_labels[x],
    key="active_tab",
    horizontal=True,
    label_visibility="collapsed",
)

st.markdown("---")


# ============================================================
# 24. TAB ÔN TẬP
# ============================================================

if selected_tab == "⏰ Ôn Tập":

    st.subheader(
        "⏰ Ôn tập đúng Thời Điểm Vàng"
    )

    now = datetime.now()

    due_items = [
        x
        for x in st.session_state.deck
        if x.get("next_review", now) <= now
    ]

    # --------------------------------------------------------
    # Không có từ
    # --------------------------------------------------------

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang **🔍 Tra Từ Mới** "
            "để thêm từ."
        )

    # --------------------------------------------------------
    # Chưa tới giờ
    # --------------------------------------------------------

    elif not due_items:

        st.session_state.review_started = False
        st.session_state.review_item = None
        st.session_state.q_type = None
        st.session_state.q_data = {}

        next_item = min(
            st.session_state.deck,
            key=lambda x: x.get(
                "next_review",
                datetime.now()
            )
        )

        remaining = (
            next_item["next_review"]
            - datetime.now()
        ).total_seconds()

        st.success(
            "🎉 Hiện tại không có từ nào "
            "đến Thời Điểm Vàng."
        )

        col1, col2 = st.columns(2)

        with col1:

            st.metric(
                "Từ tiếp theo",
                next_item["word"].upper()
            )

        with col2:

            st.metric(
                "Cấp độ",
                next_item["level"]
            )

        st.info(
            f"⏰ Còn khoảng "
            f"**{format_remaining(remaining)}**"
        )

        # ----------------------------------------------------
        # Countdown
        # ----------------------------------------------------

        target_timestamp = int(
            next_item["next_review"].timestamp()
            * 1000
        )

        countdown_html = f"""
        <div style="
            text-align:center;
            background:#262730;
            color:#00FF66;
            padding:20px;
            border-radius:15px;
            margin-top:15px;
        ">
            <div style="
                font-size:13px;
                color:#AAAAAA;
                margin-bottom:8px;
            ">
                THỜI ĐIỂM VÀNG TIẾP THEO
            </div>

            <div id="countdown"
                 style="
                    font-size:30px;
                    font-weight:bold;
                    font-family:monospace;
                 ">
                00:00:00
            </div>
        </div>

        <script>

        var targetTime = {target_timestamp};

        function updateCountdown() {{

            var currentTime =
                new Date().getTime();

            var diff =
                targetTime - currentTime;

            var element =
                document.getElementById(
                    "countdown"
                );

            if (diff <= 0) {{

                element.innerHTML =
                    "🎉 ĐÃ ĐẾN GIỜ VÀNG!";

                return;
            }}

            var totalSeconds =
                Math.floor(diff / 1000);

            var days =
                Math.floor(
                    totalSeconds / 86400
                );

            totalSeconds %= 86400;

            var hours =
                Math.floor(
                    totalSeconds / 3600
                );

            totalSeconds %= 3600;

            var minutes =
                Math.floor(
                    totalSeconds / 60
                );

            var seconds =
                totalSeconds % 60;

            hours =
                hours < 10
                ? "0" + hours
                : hours;

            minutes =
                minutes < 10
                ? "0" + minutes
                : minutes;

            seconds =
                seconds < 10
                ? "0" + seconds
                : seconds;

            if (days > 0) {{

                element.innerHTML =
                    days
                    + " ngày "
                    + hours
                    + ":"
                    + minutes
                    + ":"
                    + seconds;

            }} else {{

                element.innerHTML =
                    hours
                    + ":"
                    + minutes
                    + ":"
                    + seconds;
            }}
        }}

        updateCountdown();

        setInterval(
            updateCountdown,
            1000
        );

        </script>
        """

        st.components.v1.html(
            countdown_html,
            height=120
        )

    # --------------------------------------------------------
    # Có từ cần ôn
    # --------------------------------------------------------

    else:

        if not st.session_state.review_started:

            st.success(
                f"🔥 Có **{len(due_items)} từ** "
                "đang đến Thời Điểm Vàng."
            )

            st.markdown("---")

            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                MochiVocab sẽ chọn một từ cần ôn.
                Khi bắt đầu, thời gian phản hồi sẽ
                được tính.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review"
            ):

                # Ưu tiên cấp thấp hơn.
                min_level = min(
                    x["level"]
                    for x in due_items
                )

                candidates = [
                    x
                    for x in due_items
                    if x["level"] == min_level
                ]

                item = random.choice(
                    candidates
                )

                st.session_state.review_started = True

                prepare_review_question(
                    item
                )

                st.rerun()

        else:

            current_item = (
                st.session_state.review_item
            )

            if current_item is None:

                # Lấy lại due items mới nhất.
                due_items = get_due_items()

                if not due_items:

                    st.session_state.review_started = False
                    st.rerun()

                min_level = min(
                    x["level"]
                    for x in due_items
                )

                candidates = [
                    x
                    for x in due_items
                    if x["level"] == min_level
                ]

                item = random.choice(
                    candidates
                )

                prepare_review_question(
                    item
                )

                st.rerun()

            item = (
                st.session_state.review_item
            )

            q_type = (
                st.session_state.q_type
            )

            q_data = (
                st.session_state.q_data
            )

            # ------------------------------------------------
            # STOP
            # ------------------------------------------------

            if st.button(
                "⏹️ Dừng ôn tập",
                key="stop_review"
            ):

                st.session_state.review_started = False
                st.session_state.review_item = None
                st.session_state.q_type = None
                st.session_state.q_data = {}
                st.session_state.review_start_time = 0

                st.rerun()

            # ------------------------------------------------
            # INFO
            # ------------------------------------------------

            level = int(
                item.get("level", 0)
            )

            slot = int(
                item.get("slot", 0)
            )

            progress = (
                slot / 4
                if level > 0
                else 0
            )

            st.progress(
                progress
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(level)
                )

            with col2:

                st.caption(
                    f"Móc: "
                    f"{slot + 1}/4"
                    if level > 0
                    else "Móc: 0"
                )

            st.caption(
                f"📐 Mốc hiện tại: "
                f"**{get_current_golden_label(item)}**"
            )

            st.caption(
                f"📚 Đã ôn: "
                f"**{item.get('review_count', 0)} lần**"
            )

            st.markdown("---")

            # =================================================
            # DẠNG 1
            # =================================================

            if q_type == "CHOICE_MEANING":

                st.markdown(
                    "### 🎲 TRẮC NGHIỆM CHỌN NGHĨA"
                )

                st.info(
                    f"Từ: "
                    f"**{item['word'].upper()}** "
                    f"`{item.get('phonetic', '')}`"
                )

                if st.button(
                    "🔊 Nghe",
                    key="choice_audio"
                ):

                    play_audio_script(
                        item["word"]
                    )

                st.write(
                    "Chọn nghĩa tiếng Việt:"
                )

                for index, option in enumerate(
                    q_data.get(
                        "options",
                        []
                    )
                ):

                    if st.button(
                        option,
                        key=(
                            f"choice_"
                            f"{item['id']}_"
                            f"{index}"
                        ),
                        use_container_width=True
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # DẠNG 2
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                st.info(
                    f"**Câu:**\n\n"
                    f"{q_data.get('sentence', '')}"
                )

                user_ans = st.text_input(
                    "Từ còn thiếu:",
                    key=(
                        f"fill_"
                        f"{item['id']}"
                    )
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=(
                        f"fill_submit_"
                        f"{item['id']}"
                    ),
                    use_container_width=True
                ):

                    answer = (
                        user_ans
                        .strip()
                        .lower()
                    )

                    correct = (
                        answer
                        == item["word"]
                        .strip()
                        .lower()
                    )

                    process_answer(
                        correct,
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 3
            # =================================================

            elif q_type == "SPELLING":

                st.markdown(
                    "### ✍️ LUYỆN CHÍNH TẢ"
                )

                st.info(
                    f"Nghĩa: "
                    f"**{item['meaning'].upper()}**"
                )

                user_ans = st.text_input(
                    "Gõ từ tiếng Anh:",
                    key=(
                        f"spell_"
                        f"{item['id']}"
                    )
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=(
                        f"spell_submit_"
                        f"{item['id']}"
                    ),
                    use_container_width=True
                ):

                    answer = (
                        user_ans
                        .strip()
                        .lower()
                    )

                    correct = (
                        answer
                        == item["word"]
                        .strip()
                        .lower()
                    )

                    process_answer(
                        correct,
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 4
            # =================================================

            elif q_type == "CONTEXT_MATCH":

                st.markdown(
                    "### 🧠 NGHĨA THEO NGỮ CẢNH"
                )

                st.info(
                    f'"{q_data.get("context", "")}"'
                )

                st.write(
                    f'Từ **{item["word"].upper()}** '
                    "có nghĩa là gì?"
                )

                for index, option in enumerate(
                    q_data.get(
                        "options",
                        []
                    )
                ):

                    if st.button(
                        option,
                        key=(
                            f"context_"
                            f"{item['id']}_"
                            f"{index}"
                        ),
                        use_container_width=True
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # DẠNG 5
            # =================================================

            elif q_type == "FLASHCARD_TRUE_FALSE":

                st.markdown(
                    "### ⚡ FLASHCARD PHẢN XẠ"
                )

                st.info(
                    f"Từ: "
                    f"**{item['word'].upper()}**\n\n"
                    f"Nghĩa: "
                    f"**{q_data.get('disp_meaning', '').upper()}**"
                )

                st.write(
                    "Thông tin trên đúng hay sai?"
                )

                col1, col2 = st.columns(2)

                with col1:

                    if st.button(
                        "✅ ĐÚNG",
                        type="primary",
                        key=(
                            f"true_"
                            f"{item['id']}"
                        ),
                        use_container_width=True
                    ):

                        process_answer(
                            q_data["is_true"],
                            "ĐÚNG"
                            if q_data["is_true"]
                            else "SAI"
                        )

                with col2:

                    if st.button(
                        "❌ SAI",
                        key=(
                            f"false_"
                            f"{item['id']}"
                        ),
                        use_container_width=True
                    ):

                        process_answer(
                            not q_data["is_true"],
                            "SAI"
                            if not q_data["is_true"]
                            else "ĐÚNG"
                        )

            # =================================================
            # DẠNG 6
            # =================================================

            elif q_type == "MEANING_CHOICE":

                st.markdown(
                    "### 🔤 NGHĨA → CHỌN TỪ TIẾNG ANH"
                )

                st.info(
                    f"Nghĩa: "
                    f"**{q_data.get('question', '').upper()}**"
                )

                st.write(
                    "Chọn từ tiếng Anh:"
                )

                for index, option in enumerate(
                    q_data.get(
                        "options",
                        []
                    )
                ):

                    if st.button(
                        option.upper(),
                        key=(
                            f"mchoice_"
                            f"{item['id']}_"
                            f"{index}"
                        ),
                        use_container_width=True
                    ):

                        correct = (
                            option.lower()
                            == item["word"]
                            .lower()
                        )

                        process_answer(
                            correct,
                            item["word"].upper()
                        )


# ============================================================
# 25. TAB TRA TỪ MỚI
# ============================================================

elif selected_tab == "🔍 Tra Từ Mới":

    st.subheader(
        "🔍 Tra cứu & Thêm từ mới"
    )

    word_input = st.text_input(
        "Nhập từ tiếng Anh:",
        placeholder=(
            "Ví dụ: resilience, innovate..."
        )
    ).strip().lower()

    if st.button(
        "🔎 Tra Từ",
        type="primary",
        use_container_width=True
    ):

        if word_input:

            with st.spinner(
                "Đang tra từ..."
            ):

                data = fetch_word_full_data_FAST(
                    word_input
                )

            if not data["success"]:

                st.error(
                    f"❌ Không tìm thấy "
                    f"**{word_input}**."
                )

                st.session_state.temp_word = None

            else:

                example = (
                    data["examples"][0]
                    if data["examples"]
                    else (
                        f"It is important "
                        f"to understand "
                        f"{word_input}."
                    )
                )

                st.session_state.temp_word = {
                    "word": word_input,
                    "phonetic": data["phonetic"],
                    "meaning": data["short_vn"],
                    "example": example,
                }

    data = st.session_state.temp_word

    if (
        data is not None
        and data["word"] == word_input
    ):

        st.markdown("---")

        st.info(
            f"**{data['word'].upper()}** "
            f"`{data['phonetic']}`"
        )

        st.write(
            f"👉 **Nghĩa tiếng Việt:** "
            f"{data['meaning']}"
        )

        st.caption(
            f"💡 Ví dụ: {data['example']}"
        )

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "🔊 Nghe",
                key="new_word_audio",
                use_container_width=True
            ):

                play_audio_script(
                    data["word"]
                )

        with col2:

            if st.button(
                "➕ Thêm vào Sổ Tay",
                key="add_new_word",
                use_container_width=True
            ):

                exists = any(
                    x["word"].lower()
                    == data["word"].lower()
                    for x in st.session_state.deck
                )

                if exists:

                    st.warning(
                        "Từ này đã có."
                    )

                else:

                    # ------------------------------------------------
                    # Từ mới = Cấp 0 / 0h.
                    # ------------------------------------------------

                    new_item = {
                        "id": get_next_id(),

                        "word":
                            data["word"],

                        "phonetic":
                            data["phonetic"],

                        "meaning":
                            data["meaning"],

                        "example":
                            data["example"],

                        "level": 0,
                        "slot": 0,
                        "interval": 0,

                        "review_count": 0,
                        "correct_count": 0,
                        "wrong_count": 0,

                        "last_response_time":
                            None,

                        "last_result":
                            None,

                        "next_review":
                            datetime.now(),

                        "overdue_handled":
                            False,
                    }

                    st.session_state.deck.append(
                        new_item
                    )

                    save_deck()

                    st.success(
                        f"✅ Đã thêm "
                        f"**{data['word'].upper()}**"
                    )

                    st.info(
                        "🆕 Từ mới bắt đầu ở "
                        "**Cấp 0 — 0h**."
                    )

                    time.sleep(0.5)

                    st.rerun()


# ============================================================
# 26. TAB SỔ TAY
# ============================================================

elif selected_tab == "📋 Sổ Tay":

    st.subheader(
        "📋 Sổ tay từ vựng"
    )

    if st.session_state.deck:

        total = len(
            st.session_state.deck
        )

        due = sum(
            1
            for x in st.session_state.deck
            if x.get(
                "next_review",
                datetime.now()
            )
            <= datetime.now()
        )

        mastered = sum(
            1
            for x in st.session_state.deck
            if (
                int(x.get("level", 0))
                == MAX_LEVEL
                and int(x.get("slot", 0))
                == 3
            )
        )

        col1, col2, col3 = st.columns(3)

        with col1:

            st.metric(
                "Tổng từ",
                total
            )

        with col2:

            st.metric(
                "Cần ôn",
                due
            )

        with col3:

            st.metric(
                "Cấp 5 - 4/4",
                mastered
            )

        st.markdown("---")

        # ====================================================
        # NÚT RESET
        # ====================================================

        st.warning(
            "⚠️ Reset toàn bộ sẽ đưa tất cả từ "
            "về **Cấp 0 — 0h** và xóa thống kê ôn tập."
        )

        if st.button(
            "🔄 RESET TẤT CẢ VỀ CẤP 0",
            key="reset_all_level_zero",
            type="secondary",
            use_container_width=True
        ):

            reset_all_to_level_zero()

            st.success(
                "✅ Đã reset toàn bộ từ về "
                "Cấp 0 — 0h."
            )

            time.sleep(0.5)

            st.rerun()

        st.markdown("---")

        # ====================================================
        # TABLE
        # ====================================================

        table_data = []

        for item in st.session_state.deck:

            next_review = item.get(
                "next_review",
                datetime.now()
            )

            remaining = (
                next_review
                - datetime.now()
            ).total_seconds()

            if remaining <= 0:

                status = (
                    "🔥 Sẵn sàng ôn!"
                )

            else:

                status = (
                    "⏳ "
                    + format_remaining(
                        remaining
                    )
                )

            accuracy_total = (
                int(
                    item.get(
                        "correct_count",
                        0
                    )
                )
                +
                int(
                    item.get(
                        "wrong_count",
                        0
                    )
                )
            )

            # ------------------------------------------------
            # FIX LỖI accuracy_text
            # ------------------------------------------------

            if accuracy_total > 0:

                accuracy_value = (
                    int(
                        item.get(
                            "correct_count",
                            0
                        )
                    )
                    / accuracy_total
                    * 100
                )

                accuracy_text = (
                    f"{accuracy_value:.0f}%"
                )

            else:

                accuracy_text = "—"

            # ------------------------------------------------
            # Golden label
            # ------------------------------------------------

            golden_label = (
                get_current_golden_label(
                    item
                )
            )

            table_data.append({
                "Từ":
                    item["word"].upper(),

                "Nghĩa":
                    item["meaning"],

                "Cấp":
                    item["level"],

                "Móc":
                    (
                        f"{item['slot'] + 1}/4"
                        if item["level"] > 0
                        else "0/4"
                    ),

                "Thời Điểm Vàng":
                    golden_label,

                "Trạng thái":
                    get_level_name(
                        item["level"]
                    ),

                "Độ chính xác":
                    accuracy_text,

                "Số lần ôn":
                    item.get(
                        "review_count",
                        0
                    ),

                "Tiếp theo":
                    status,
            })

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        # ====================================================
        # HIỂN THỊ BẢNG CÁC MỐC
        # ====================================================

        st.markdown(
            "### 🧠 Hệ thống Thời Điểm Vàng"
        )

        st.write(
            "Mỗi cấp có 4 móc. Đủ 4 móc sẽ lên cấp."
        )

        for level in range(
            1,
            MAX_LEVEL + 1
        ):

            slots = GOLDEN_HOURS[level]

            st.write(
                f"**Cấp {level}:** "
                f"{slots[0]}h → "
                f"{slots[1]}h → "
                f"{slots[2]}h → "
                f"{slots[3]}h"
            )

        st.markdown("---")

        # ====================================================
        # DELETE ALL
        # ====================================================

        st.warning(
            "Xóa toàn bộ sẽ xóa vĩnh viễn "
            "toàn bộ từ trong LocalStorage."
        )

        if st.button(
            "🗑️ XÓA TOÀN BỘ TỪ VỰNG",
            key="delete_all_words",
            use_container_width=True
        ):

            st.session_state.deck = []

            st.session_state.review_item = None

            st.session_state.review_started = False

            st.session_state.q_type = None

            st.session_state.q_data = {}

            st.session_state.temp_word = None

            save_deck()

            st.success(
                "Đã xóa toàn bộ dữ liệu."
            )

            time.sleep(0.5)

            st.rerun()

    else:

        st.info(
            "📚 Sổ tay đang trống."
        )


# ============================================================
# 27. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • Dynamic Golden Time"
)
