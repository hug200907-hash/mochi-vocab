import json
import random
import time
import urllib.parse
import urllib.request
import re

from datetime import datetime, timedelta

import requests
import streamlit as st
from streamlit_local_storage import LocalStorage
from streamlit_autorefresh import st_autorefresh


# ============================================================
# 1. CẤU HÌNH APP
# ============================================================

st.set_page_config(
    page_title="MochiVocab",
    page_icon="🍌",
    layout="centered"
)

local_storage = LocalStorage()

# Tự kiểm tra app mỗi 5 phút
st_autorefresh(
    interval=5 * 60 * 1000,
    key="mochi_auto_refresh"
)


# ============================================================
# 2. HỆ THỐNG MÓC
# ============================================================
#
# Cấp 0:
#   - Từ mới thêm vào
#   - Móc 0 = 0 giờ
#
# Cấp 1:
#   Móc 1 = 1h
#   Móc 2 = 4h
#   Móc 3 = 12h
#   Móc 4 = 24h
#
# Cấp 2:
#   25h → 28h → 36h → 48h
#
# Cấp 3:
#   49h → 52h → 60h → 72h
#
# Cấp 4:
#   73h → 76h → 84h → 96h
#
# Cấp 5:
#   97h → 100h → 108h → 120h
#
# Sau móc 4 của một cấp:
#   → lên cấp tiếp theo
#   → đồng thời chuyển sang móc đầu tiên của cấp mới
#
# Sai:
#   → lùi 1 móc
#   → KHÔNG BAO GIỜ từ cấp 1 móc 1h rơi về cấp 0
#
# Quá hạn:
#   → lùi 1 móc
#   → KHÔNG BAO GIỜ rơi về cấp 0
#

LEVEL_HOOKS = {
    0: [0],
    1: [1, 4, 12, 24],
    2: [25, 28, 36, 48],
    3: [49, 52, 60, 72],
    4: [73, 76, 84, 96],
    5: [97, 100, 108, 120],
}

MIN_LEVEL = 0
MAX_LEVEL = 5


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
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 4. FORMAT THỜI GIAN
# ============================================================

def format_hours(hours):
    hours = float(hours)

    if hours == 0:
        return "0 giờ"

    if hours.is_integer():
        return f"{int(hours)} giờ"

    return f"{hours:.1f} giờ"


def format_remaining(seconds):
    seconds = int(max(0, seconds))

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days} ngày {hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# ============================================================
# 5. THÔNG TIN CẤP
# ============================================================

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


def get_hook_name(level, hook):
    if level == 0:
        return "Móc 0"

    return f"Móc {hook}/4"


def get_current_hours(item):
    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

    if level == 0:
        return 0

    hooks = LEVEL_HOOKS.get(level, LEVEL_HOOKS[1])

    hook = max(1, min(hook, 4))

    return hooks[hook - 1]


# ============================================================
# 6. CHUẨN HÓA DỮ LIỆU CŨ
# ============================================================

def migrate_item(item):
    """
    Chuyển dữ liệu cũ sang hệ thống level + hook mới.
    """

    try:
        level = int(item.get("level", 0))
    except Exception:
        level = 0

    level = max(0, min(level, 5))

    # Nếu dữ liệu cũ chưa có hook
    if "hook" not in item:
        old_interval = float(item.get("interval", 0))

        if level == 0:
            hook = 0

        else:
            hooks = LEVEL_HOOKS[level]

            hook = 1

            for i, hours in enumerate(hooks, start=1):
                if old_interval >= hours * 60:
                    hook = i

        item["hook"] = hook

    try:
        hook = int(item.get("hook", 0))
    except Exception:
        hook = 0

    if level == 0:
        hook = 0
    else:
        hook = max(1, min(hook, 4))

    item["level"] = level
    item["hook"] = hook

    # Interval tính bằng phút
    item["interval"] = get_current_hours(item) * 60

    item["review_count"] = int(item.get("review_count", 0))
    item["correct_count"] = int(item.get("correct_count", 0))
    item["wrong_count"] = int(item.get("wrong_count", 0))

    item["last_response_time"] = item.get(
        "last_response_time",
        None
    )

    item["last_result"] = item.get(
        "last_result",
        None
    )

    # next_review
    if "next_review" not in item:
        if level == 0:
            item["next_review"] = datetime.now()
        else:
            item["next_review"] = (
                datetime.now()
                + timedelta(hours=get_current_hours(item))
            )

    elif isinstance(item["next_review"], str):
        try:
            item["next_review"] = datetime.fromisoformat(
                item["next_review"]
            )
        except Exception:
            item["next_review"] = datetime.now()

    return item


# ============================================================
# 7. LOAD LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:

    saved_data = local_storage.getItem(
        "mochi_deck_data"
    )

    if saved_data:

        try:
            items = json.loads(saved_data)

            cleaned_items = []

            for item in items:

                item = migrate_item(item)

                cleaned_items.append(item)

            st.session_state.deck = cleaned_items

        except Exception:
            st.session_state.deck = []

    st.session_state.data_loaded = True


# ============================================================
# 8. SAVE LOCAL STORAGE
# ============================================================

def save_deck():

    serializable_deck = []

    for item in st.session_state.deck:

        copy_item = item.copy()

        if isinstance(
            copy_item.get("next_review"),
            datetime
        ):
            copy_item["next_review"] = (
                copy_item["next_review"].isoformat()
            )

        serializable_deck.append(copy_item)

    local_storage.setItem(
        "mochi_deck_data",
        json.dumps(
            serializable_deck,
            ensure_ascii=False
        )
    )


# ============================================================
# 9. AUDIO
# ============================================================

def play_audio_script(word):

    safe_word = (
        word.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", " ")
        .replace("\r", " ")
    )

    js_code = f"""
    <script>
    window.speechSynthesis.cancel();

    var msg = new SpeechSynthesisUtterance(
        '{safe_word}'
    );

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
# 10. DỊCH ANH → VIỆT
# ============================================================

def translate_single_text(text):

    if not text or not text.strip():
        return ""

    text = text.strip()

    try:

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
            "?client=gtx"
            "&sl=en"
            "&tl=vi"
            "&dt=t"
            "&q="
            + urllib.parse.quote(text)
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
                response.read().decode(
                    "utf-8"
                )
            )

            translated = "".join(
                part[0]
                for part in data[0]
                if part and part[0]
            )

            return translated.strip()

    except Exception:
        return ""


# ============================================================
# 11. OXFORD EXAMPLE
# ============================================================

def fetch_oxford_example(word):
    """
    Cố gắng lấy câu ví dụ từ Oxford Learner's Dictionaries.

    Oxford có dữ liệu example sentences trên trang từ điển.
    Nếu không lấy được thì trả None.
    """

    try:

        encoded_word = urllib.parse.quote(
            word
        )

        url = (
            "https://www.oxfordlearnersdictionaries.com/"
            "definition/english/"
            + encoded_word
        )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120 Safari/537.36"
            )
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=6
        )

        if response.status_code != 200:
            return None

        html = response.text

        # Oxford thường có class example
        patterns = [
            r'<span class="x">(.+?)</span>',
            r'<span class="examples__item">(.+?)</span>',
            r'<div class="examples">(.+?)</div>',
        ]

        for pattern in patterns:

            matches = re.findall(
                pattern,
                html,
                flags=re.IGNORECASE |
                re.DOTALL
            )

            for match in matches:

                clean = re.sub(
                    r"<[^>]+>",
                    " ",
                    match
                )

                clean = (
                    clean
                    .replace("&apos;", "'")
                    .replace("&quot;", '"')
                    .replace("&amp;", "&")
                )

                clean = re.sub(
                    r"\s+",
                    " ",
                    clean
                ).strip()

                if (
                    len(clean) > 10
                    and len(clean) < 500
                ):
                    return clean

    except Exception:
        pass

    return None


# ============================================================
# 12. DICTIONARY API
# ============================================================

def fetch_dictionary_data(word):

    url = (
        "https://api.dictionaryapi.dev/"
        "api/v2/entries/en/"
        + urllib.parse.quote(word)
    )

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
                response.read().decode(
                    "utf-8"
                )
            )

            if not isinstance(data, list):
                return None

            if not data:
                return None

            first = data[0]

            phonetic = (
                first.get("phonetic")
                or f"/{word}/"
            )

            examples = []

            for meaning in first.get(
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
                        examples.append(
                            example
                        )

            return {
                "phonetic": phonetic,
                "examples": examples,
            }

    except Exception:
        return None


# ============================================================
# 13. TRA TỪ ĐẦY ĐỦ
# ============================================================

def fetch_word_full_data(word):

    word = word.strip().lower()

    dictionary_data = fetch_dictionary_data(
        word
    )

    if dictionary_data is None:
        return {
            "success": False
        }

    # --------------------------------------------------------
    # Nghĩa Việt
    # --------------------------------------------------------

    vietnamese_meaning = translate_single_text(
        word
    )

    # Nếu dịch lỗi thì thử dịch definition
    if not vietnamese_meaning:

        try:

            definition_text = ""

            url = (
                "https://api.dictionaryapi.dev/"
                "api/v2/entries/en/"
                + urllib.parse.quote(word)
            )

            response = requests.get(
                url,
                timeout=5
            )

            data = response.json()

            definition_text = (
                data[0]["meanings"][0]
                ["definitions"][0]
                ["definition"]
            )

            vietnamese_meaning = (
                translate_single_text(
                    definition_text
                )
            )

        except Exception:
            pass

    if not vietnamese_meaning:
        vietnamese_meaning = "Chưa dịch được"

    # --------------------------------------------------------
    # Example Oxford trước
    # --------------------------------------------------------

    example = fetch_oxford_example(
        word
    )

    # Nếu Oxford không lấy được → Dictionary API
    if not example:

        examples = dictionary_data.get(
            "examples",
            []
        )

        if examples:
            example = examples[0]

    # Cuối cùng mới tạo example fallback
    if not example:
        example = (
            f"I want to learn how to use "
            f"the word {word} correctly."
        )

    return {
        "success": True,
        "word": word,
        "phonetic": dictionary_data.get(
            "phonetic",
            f"/{word}/"
        ),
        "meaning": vietnamese_meaning,
        "example": example,
    }


# ============================================================
# 14. ID
# ============================================================

def get_next_id():

    if not st.session_state.deck:
        return 1

    return (
        max(
            int(x.get("id", 0))
            for x in st.session_state.deck
        )
        + 1
    )


# ============================================================
# 15. TÍNH MÓC TIẾP THEO KHI ĐÚNG
# ============================================================

def advance_hook(item):

    level = int(
        item.get("level", 0)
    )

    hook = int(
        item.get("hook", 0)
    )

    # -----------------------------------------
    # Từ mới → cấp 1 móc 1
    # -----------------------------------------

    if level == 0:

        item["level"] = 1
        item["hook"] = 1

        return {
            "level_up": True,
            "old_level": 0,
            "new_level": 1,
            "old_hook": 0,
            "new_hook": 1,
        }

    # -----------------------------------------
    # Chưa tới móc 4
    # -----------------------------------------

    if hook < 4:

        item["hook"] = hook + 1

        return {
            "level_up": False,
            "old_level": level,
            "new_level": level,
            "old_hook": hook,
            "new_hook": hook + 1,
        }

    # -----------------------------------------
    # Móc 4 → lên cấp
    # -----------------------------------------

    if level < MAX_LEVEL:

        item["level"] = level + 1
        item["hook"] = 1

        return {
            "level_up": True,
            "old_level": level,
            "new_level": level + 1,
            "old_hook": hook,
            "new_hook": 1,
        }

    # -----------------------------------------
    # Cấp 5 móc 4 → giữ nguyên
    # -----------------------------------------

    item["level"] = 5
    item["hook"] = 4

    return {
        "level_up": False,
        "old_level": 5,
        "new_level": 5,
        "old_hook": 4,
        "new_hook": 4,
    }


# ============================================================
# 16. LÙI MÓC KHI SAI / QUÁ HẠN
# ============================================================

def decrease_hook(item):

    level = int(
        item.get("level", 0)
    )

    hook = int(
        item.get("hook", 0)
    )

    # -----------------------------------------
    # Cấp 0 không lùi
    # -----------------------------------------

    if level <= 0:

        item["level"] = 0
        item["hook"] = 0

        return {
            "level": 0,
            "hook": 0,
            "changed": False,
        }

    # -----------------------------------------
    # Móc > 1 → lùi 1 móc
    # -----------------------------------------

    if hook > 1:

        item["hook"] = hook - 1

        return {
            "level": level,
            "hook": hook - 1,
            "changed": True,
        }

    # -----------------------------------------
    # Móc 1 → KHÔNG xuống cấp 0
    #
    # Ví dụ:
    # Cấp 2 móc 1 → Cấp 1 móc 4
    # Cấp 1 móc 1 → vẫn Cấp 1 móc 1
    # -----------------------------------------

    if level > 1:

        item["level"] = level - 1
        item["hook"] = 4

        return {
            "level": level - 1,
            "hook": 4,
            "changed": True,
        }

    # Cấp 1 móc 1
    # Không được về cấp 0

    item["level"] = 1
    item["hook"] = 1

    return {
        "level": 1,
        "hook": 1,
        "changed": False,
    }


# ============================================================
# 17. ĐẶT LỊCH ÔN
# ============================================================

def schedule_item(item):

    hours = get_current_hours(item)

    item["interval"] = hours * 60

    item["next_review"] = (
        datetime.now()
        + timedelta(hours=hours)
    )


# ============================================================
# 18. RESET MỘT TỪ VỀ MÓC 0
# ============================================================

def reset_item_to_zero(item):

    item["level"] = 0
    item["hook"] = 0
    item["interval"] = 0

    item["next_review"] = datetime.now()

    item["review_count"] = 0
    item["correct_count"] = 0
    item["wrong_count"] = 0

    item["last_response_time"] = None
    item["last_result"] = None

    item["overdue_count"] = 0


# ============================================================
# 19. RESET TẤT CẢ
# ============================================================

def reset_all_items():

    for item in st.session_state.deck:
        reset_item_to_zero(item)

    save_deck()

    st.session_state.review_item = None
    st.session_state.review_started = False
    st.session_state.q_type = None
    st.session_state.q_data = {}


# ============================================================
# 20. TỰ ĐỘNG HẠ MÓC KHI QUÁ HẠN
# ============================================================

def process_overdue_items():

    now = datetime.now()

    changed = False

    for item in st.session_state.deck:

        next_review = item.get(
            "next_review"
        )

        if not isinstance(
            next_review,
            datetime
        ):
            continue

        if next_review <= now:

            # Nếu đã đến giờ và chưa làm,
            # hạ 1 móc.
            #
            # Nhưng tránh hạ liên tục mỗi lần
            # app rerun.
            last_overdue = item.get(
                "last_overdue_check"
            )

            already_processed = False

            if last_overdue:

                try:

                    last_dt = datetime.fromisoformat(
                        last_overdue
                    )

                    if (
                        now - last_dt
                    ).total_seconds() < 5 * 60:
                        already_processed = True

                except Exception:
                    pass

            if already_processed:
                continue

            result = decrease_hook(item)

            item["overdue_count"] = (
                int(
                    item.get(
                        "overdue_count",
                        0
                    )
                )
                + 1
            )

            item["last_overdue_check"] = (
                now.isoformat()
            )

            # Đặt lịch lại theo móc mới
            schedule_item(item)

            changed = True

    if changed:
        save_deck()


# Chạy kiểm tra quá hạn
process_overdue_items()


# ============================================================
# 21. TẠO CÂU HỎI
# ============================================================
#
# BỎ:
# - Audio choice
#
# Còn:
# 1. Từ → chọn nghĩa
# 2. Điền từ vào chỗ trống
# 3. Nghĩa → gõ từ
# 4. Ngữ cảnh → chọn nghĩa
# 5. Đúng / Sai
# 6. Nghĩa → chọn từ
#

def prepare_review_question(item):

    q_types = [
        "CHOICE_MEANING",
        "FILL_BLANK",
        "SPELLING",
        "CONTEXT_MATCH",
        "FLASHCARD_TRUE_FALSE",
        "MEANING_CHOICE",
    ]

    chosen_q = random.choice(
        q_types
    )

    st.session_state.review_item = item
    st.session_state.q_type = chosen_q
    st.session_state.review_start_time = (
        time.time()
    )
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

    if not example:

        example = (
            f"I want to learn "
            f"the word {word}."
        )

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
    # 1. TỪ → CHỌN NGHĨA
    # ========================================================

    if chosen_q == "CHOICE_MEANING":

        options = [meaning]

        distractors = random.sample(
            deck_meanings,
            min(
                len(deck_meanings),
                3
            )
        )

        for d in distractors:

            if d not in options:
                options.append(d)

        fallback_meanings = [
            "sự phát triển",
            "khả năng thích nghi",
            "thành tựu",
            "môi trường",
            "kinh nghiệm",
            "sự thay đổi",
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

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

        # Không phân biệt hoa thường
        pattern = re.compile(
            re.escape(word),
            re.IGNORECASE
        )

        blank_sentence = pattern.sub(
            "_____",
            example
        )

        # Nếu example không chứa từ
        if blank_sentence == example:

            blank_sentence = (
                f"{example} "
                f"(_____)"
            )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word,
        }

    # ========================================================
    # 3. NGHĨA → GÕ TỪ
    # ========================================================

    elif chosen_q == "SPELLING":

        st.session_state.q_data = {
            "question": meaning,
            "answer": word,
        }

    # ========================================================
    # 4. NGỮ CẢNH → CHỌN NGHĨA
    # ========================================================

    elif chosen_q == "CONTEXT_MATCH":

        options = [meaning]

        distractors = random.sample(
            deck_meanings,
            min(
                len(deck_meanings),
                3
            )
        )

        for d in distractors:

            if d not in options:
                options.append(d)

        fallback_meanings = [
            "sự phát triển",
            "khả năng thích nghi",
            "thành tựu",
            "môi trường",
            "kinh nghiệm",
            "sự thay đổi",
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

        random.shuffle(options)

        st.session_state.q_data = {
            "context": example,
            "word": word,
            "options": options,
            "answer": meaning,
        }

    # ========================================================
    # 5. FLASHCARD ĐÚNG / SAI
    # ========================================================

    elif chosen_q == "FLASHCARD_TRUE_FALSE":

        is_true = random.choice(
            [True, False]
        )

        if (
            is_true
            or not deck_meanings
        ):

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
    # 6. NGHĨA → CHỌN TỪ
    # ========================================================

    elif chosen_q == "MEANING_CHOICE":

        options = [word]

        sampled_words = random.sample(
            deck_words,
            min(
                len(deck_words),
                3
            )
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
        ]

        for fb in fallback_words:

            if len(options) >= 4:
                break

            if fb.lower() not in [
                x.lower()
                for x in options
            ]:
                options.append(fb)

        random.shuffle(options)

        st.session_state.q_data = {
            "word": word,
            "question": meaning,
            "options": options,
            "answer": word,
        }


# ============================================================
# 22. XỬ LÝ CÂU TRẢ LỜI
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

    old_hook = int(
        item.get("hook", 0)
    )

    item["review_count"] = (
        int(
            item.get(
                "review_count",
                0
            )
        )
        + 1
    )

    item["last_response_time"] = round(
        response_time,
        2
    )

    item["last_result"] = (
        "correct"
        if is_correct
        else "wrong"
    )

    if is_correct:

        item["correct_count"] = (
            int(
                item.get(
                    "correct_count",
                    0
                )
            )
            + 1
        )

        result = advance_hook(item)

        schedule_item(item)

        new_level = int(
            item["level"]
        )

        new_hook = int(
            item["hook"]
        )

        st.success(
            "✨ Chính xác!"
        )

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        if result["level_up"]:

            st.success(
                f"📈 Lên cấp: "
                f"{old_level} → {new_level}"
            )

        else:

            st.info(
                f"📌 Móc: "
                f"{old_hook} → {new_hook}"
            )

        st.info(
            f"🧠 Móc tiếp theo: "
            f"**{format_hours(get_current_hours(item))}**"
        )

        if new_level == 5 and new_hook == 4:

            st.balloons()

            st.success(
                "🏆 Đã đạt Cấp 5 - Móc 4!"
            )

    else:

        item["wrong_count"] = (
            int(
                item.get(
                    "wrong_count",
                    0
                )
            )
            + 1
        )

        result = decrease_hook(item)

        schedule_item(item)

        new_level = int(
            item["level"]
        )

        new_hook = int(
            item["hook"]
        )

        st.error(
            "❌ Chưa chính xác."
        )

        st.warning(
            f"Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        if (
            old_level == 1
            and old_hook == 1
        ):

            st.warning(
                "🛡️ Đây là Cấp 1 - Móc 1. "
                "Sai nhưng không rơi về Cấp 0."
            )

        elif (
            old_hook > 1
        ):

            st.warning(
                f"📉 Móc: "
                f"{old_hook} → {new_hook}"
            )

        else:

            st.warning(
                f"📉 Cấp: "
                f"{old_level} → {new_level}, "
                f"Móc → {new_hook}"
            )

        st.info(
            f"🔄 Câu hỏi mới sẽ được tạo "
            f"cho từ **{item['word'].upper()}**."
        )

    save_deck()

    # Không giữ câu hỏi cũ
    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    time.sleep(1.0)

    st.rerun()


# ============================================================
# 23. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Hệ thống học theo Cấp + 4 Móc"
)

now = datetime.now()

due_count = sum(
    1
    for x in st.session_state.deck
    if x.get("next_review") <= now
)


# ============================================================
# 24. MENU
# ============================================================

tab_options = [
    "⏰ Ôn Tập",
    "🔍 Tra Từ Mới",
    "📋 Sổ Tay",
]

tab_labels = {
    "⏰ Ôn Tập":
        f"⏰ Ôn Tập ({due_count})",

    "🔍 Tra Từ Mới":
        "🔍 Tra Từ Mới",

    "📋 Sổ Tay":
        f"📋 Sổ Tay ({len(st.session_state.deck)})",
}

selected_tab = st.radio(
    "Navigation",
    options=tab_options,
    format_func=lambda x:
        tab_labels[x],
    key="active_tab",
    horizontal=True,
    label_visibility="collapsed",
)

st.markdown("---")


# ============================================================
# 25. TAB ÔN TẬP
# ============================================================

if selected_tab == "⏰ Ôn Tập":

    st.subheader(
        "⏰ Ôn tập theo Thời Điểm Vàng"
    )

    now = datetime.now()

    due_items = [
        x
        for x in st.session_state.deck
        if x.get("next_review") <= now
    ]

    # --------------------------------------------------------
    # Không có từ
    # --------------------------------------------------------

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang "
            "**🔍 Tra Từ Mới** "
            "để thêm từ."
        )

    # --------------------------------------------------------
    # Không có từ cần ôn
    # --------------------------------------------------------

    elif not due_items:

        st.session_state.review_started = False
        st.session_state.review_item = None
        st.session_state.q_type = None
        st.session_state.q_data = {}

        next_item = min(
            st.session_state.deck,
            key=lambda x:
                x["next_review"]
        )

        remaining = (
            next_item["next_review"]
            - datetime.now()
        ).total_seconds()

        st.success(
            "🎉 Hiện tại không có "
            "từ nào đến giờ ôn."
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Từ tiếp theo",
                next_item["word"].upper()
            )

        with col2:
            st.metric(
                "Cấp",
                next_item["level"]
            )

        with col3:
            st.metric(
                "Móc",
                next_item.get("hook", 0)
            )

        st.info(
            f"⏰ Còn khoảng "
            f"**{format_remaining(remaining)}**"
        )

    # --------------------------------------------------------
    # Có từ cần ôn
    # --------------------------------------------------------

    else:

        if not st.session_state.review_started:

            st.success(
                f"🔥 Có **{len(due_items)} từ** "
                f"đang đến giờ ôn."
            )

            st.markdown("---")

            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                MochiVocab sẽ chọn một từ cần ôn,
                sau đó tính thời gian phản hồi.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review",
            ):

                # Ưu tiên cấp thấp trước
                min_level = min(
                    x["level"]
                    for x in due_items
                )

                candidates = [
                    x
                    for x in due_items
                    if x["level"]
                    == min_level
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

            # Nếu không còn câu hỏi
            if current_item is None:

                now = datetime.now()

                due_items = [
                    x
                    for x in st.session_state.deck
                    if x.get("next_review")
                    <= now
                ]

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
                    if x["level"]
                    == min_level
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
                key="stop_review",
            ):

                st.session_state.review_started = False
                st.session_state.review_item = None
                st.session_state.q_type = None
                st.session_state.q_data = {}

                st.rerun()

            # ------------------------------------------------
            # THÔNG TIN TỪ
            # ------------------------------------------------

            level = int(
                item.get(
                    "level",
                    0
                )
            )

            hook = int(
                item.get(
                    "hook",
                    0
                )
            )

            st.progress(
                level / 5
            )

            col1, col2, col3 = st.columns(3)

            with col1:

                st.caption(
                    get_level_name(
                        level
                    )
                )

            with col2:

                st.caption(
                    get_hook_name(
                        level,
                        hook
                    )
                )

            with col3:

                st.caption(
                    f"Đã ôn: "
                    f"{item.get('review_count', 0)}"
                )

            st.markdown(
                f"""
                **{item['word'].upper()}**
                `{item.get('phonetic', '')}`

                📌 Cấp **{level}**
                · Móc **{hook}/4**
                """
            )

            if level == 0:

                st.info(
                    "🆕 Từ mới — Móc 0 — 0 giờ"
                )

            else:

                st.info(
                    f"⏱️ Móc hiện tại: "
                    f"**{format_hours(get_current_hours(item))}**"
                )

            st.markdown("---")

            # =================================================
            # CÂU 1
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
                        use_container_width=True,
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # CÂU 2
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
                    ),
                )

                if st.button(
                    "Xác nhận",
                    type="primary",
                    key=(
                        f"fill_submit_"
                        f"{item['id']}"
                    ),
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].strip().lower(),
                        item["word"].upper()
                    )

            # =================================================
            # CÂU 3
            # =================================================

            elif q_type == "SPELLING":

                st.markdown(
                    "### ✍️ NGHĨA → GÕ TỪ"
                )

                st.info(
                    f"Nghĩa tiếng Việt:\n\n"
                    f"**{item['meaning'].upper()}**"
                )

                user_ans = st.text_input(
                    "Gõ từ tiếng Anh:",
                    key=(
                        f"spell_"
                        f"{item['id']}"
                    ),
                )

                if st.button(
                    "Xác nhận",
                    type="primary",
                    key=(
                        f"spell_submit_"
                        f"{item['id']}"
                    ),
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].strip().lower(),
                        item["word"].upper()
                    )

            # =================================================
            # CÂU 4
            # =================================================

            elif q_type == "CONTEXT_MATCH":

                st.markdown(
                    "### 🧠 NGHĨA THEO NGỮ CẢNH"
                )

                st.info(
                    f"\"{q_data.get('context', '')}\""
                )

                st.write(
                    f"Từ "
                    f"**{item['word'].upper()}** "
                    f"có nghĩa là gì?"
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
                        use_container_width=True,
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # CÂU 5
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
                        use_container_width=True,
                    ):

                        process_answer(
                            q_data["is_true"],
                            (
                                "ĐÚNG"
                                if q_data["is_true"]
                                else "SAI"
                            )
                        )

                with col2:

                    if st.button(
                        "❌ SAI",
                        key=(
                            f"false_"
                            f"{item['id']}"
                        ),
                        use_container_width=True,
                    ):

                        process_answer(
                            not q_data["is_true"],
                            (
                                "SAI"
                                if not q_data["is_true"]
                                else "ĐÚNG"
                            )
                        )

            # =================================================
            # CÂU 6
            # =================================================

            elif q_type == "MEANING_CHOICE":

                st.markdown(
                    "### 🔤 NGHĨA → CHỌN TỪ"
                )

                st.info(
                    f"Nghĩa:\n\n"
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
                        use_container_width=True,
                    ):

                        process_answer(
                            option.lower()
                            == item["word"].lower(),
                            item["word"].upper()
                        )


# ============================================================
# 26. TAB TRA TỪ
# ============================================================

elif selected_tab == "🔍 Tra Từ Mới":

    st.subheader(
        "🔍 Tra cứu & Thêm từ mới"
    )

    word_input = st.text_input(
        "Nhập từ tiếng Anh:",
        placeholder=(
            "Ví dụ: resilience, innovate..."
        ),
    ).strip().lower()

    if st.button(
        "🔎 Tra Từ",
        type="primary"
    ):

        if word_input:

            with st.spinner(
                "Đang tra từ..."
            ):

                data = fetch_word_full_data(
                    word_input
                )

            if not data["success"]:

                st.error(
                    f"❌ Không tìm thấy "
                    f"**{word_input}**."
                )

                st.session_state.temp_word = None

            else:

                st.session_state.temp_word = data

    data = st.session_state.temp_word

    if (
        data is not None
        and data.get("word") == word_input
    ):

        st.markdown("---")

        st.markdown(
            f"## {data['word'].upper()}"
        )

        st.caption(
            data.get(
                "phonetic",
                ""
            )
        )

        # Quan trọng:
        # Hiển thị nghĩa Việt
        st.success(
            f"🇻🇳 Nghĩa tiếng Việt: "
            f"**{data['meaning']}**"
        )

        st.caption(
            f"💡 Ví dụ: "
            f"{data['example']}"
        )

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "🔊 Nghe",
                key="new_word_audio",
                use_container_width=True,
            ):

                play_audio_script(
                    data["word"]
                )

        with col2:

            if st.button(
                "➕ Thêm vào Sổ Tay",
                key="add_new_word",
                use_container_width=True,
            ):

                exists = any(
                    x["word"].lower()
                    == data["word"].lower()
                    for x in st.session_state.deck
                )

                if exists:

                    st.warning(
                        "Từ này đã có trong sổ tay."
                    )

                else:

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

                        # Từ mới = cấp 0
                        "level": 0,

                        # Móc 0
                        "hook": 0,

                        # 0 giờ
                        "interval": 0,

                        "review_count": 0,

                        "correct_count": 0,

                        "wrong_count": 0,

                        "last_response_time":
                            None,

                        "last_result":
                            None,

                        "overdue_count":
                            0,

                        "last_overdue_check":
                            None,

                        # Ôn ngay
                        "next_review":
                            datetime.now(),
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
                        "🆕 Từ mới bắt đầu "
                        "ở Cấp 0 - Móc 0."
                    )

                    time.sleep(0.7)

                    st.rerun()


# ============================================================
# 27. TAB SỔ TAY
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
            if x.get("next_review")
            <= datetime.now()
        )

        mastered = sum(
            1
            for x in st.session_state.deck
            if (
                x.get("level") == 5
                and x.get("hook") == 4
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
                "Đã max",
                mastered
            )

        st.markdown("---")

        # ====================================================
        # BẢNG
        # ====================================================

        table_data = []

        for item in st.session_state.deck:

            remaining = (
                item["next_review"]
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

            correct = int(
                item.get(
                    "correct_count",
                    0
                )
            )

            wrong = int(
                item.get(
                    "wrong_count",
                    0
                )
            )

            accuracy_total = (
                correct + wrong
            )

            # SỬA LỖI ACCURACY
            if accuracy_total > 0:

                accuracy_text = (
                    f"{correct / accuracy_total * 100:.0f}%"
                )

            else:

                accuracy_text = "—"

            level = int(
                item.get(
                    "level",
                    0
                )
            )

            hook = int(
                item.get(
                    "hook",
                    0
                )
            )

            table_data.append(
                {
                    "Từ":
                        item["word"].upper(),

                    "Nghĩa":
                        item["meaning"],

                    "Cấp":
                        level,

                    "Móc":
                        (
                            "0"
                            if level == 0
                            else f"{hook}/4"
                        ),

                    "Cấp độ":
                        get_level_name(
                            level
                        ),

                    "Móc hiện tại":
                        (
                            "0 giờ"
                            if level == 0
                            else format_hours(
                                get_current_hours(
                                    item
                                )
                            )
                        ),

                    "Độ chính xác":
                        accuracy_text,

                    "Số lần ôn":
                        item.get(
                            "review_count",
                            0
                        ),

                    "Trạng thái":
                        status,
                }
            )

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")

        # ====================================================
        # RESET ALL
        # ====================================================

        st.markdown(
            "### 🔄 Đặt lại tiến độ"
        )

        st.warning(
            "Nút này sẽ đưa toàn bộ từ về "
            "**Cấp 0 - Móc 0 - 0 giờ**."
        )

        if st.button(
            "🔄 RESET ALL VỀ MÓC 0",
            type="secondary",
            use_container_width=True,
            key="reset_all",
        ):

            reset_all_items()

            st.success(
                "✅ Đã reset toàn bộ từ "
                "về Cấp 0 - Móc 0."
            )

            time.sleep(0.5)

            st.rerun()

        st.markdown("---")

        # ====================================================
        # DELETE ALL
        # ====================================================

        if st.button(
            "🗑️ Xóa toàn bộ từ vựng",
            key="delete_all_words",
            use_container_width=True,
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
# 28. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • "
    "Level + 4 Hook Spaced Repetition"
)
