import json
import random
import time
import urllib.parse
import urllib.request
import urllib.error
import re

from datetime import datetime, timedelta

import streamlit as st
from streamlit_local_storage import LocalStorage


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
# 2. HỆ THỐNG CẤP + MÓC
# ============================================================

LEVEL_HOOKS = {
    1: [1, 4, 12, 24],
    2: [25, 28, 36, 48],
    3: [49, 52, 60, 72],
    4: [73, 76, 84, 96],
    5: [97, 100, 108, 120],
}

MAX_LEVEL = 5
HOOKS_PER_LEVEL = 4


# ============================================================
# 3. SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "deck": [],
    "data_loaded": False,
    "review_item": None,
    "q_type": None,
    "q_data": {},
    "review_start_time": 0.0,
    "active_tab": "⏰ Ôn Tập",
    "temp_word": None,
    "review_started": False,
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
# 4. FORMAT
# ============================================================

def format_hours(hours):

    hours = float(hours)

    if hours.is_integer():
        return f"{int(hours)} giờ"

    return f"{hours:.1f} giờ"


def format_remaining(seconds):

    seconds = int(max(0, seconds))

    days, remainder = divmod(
        seconds,
        86400
    )

    hours, remainder = divmod(
        remainder,
        3600
    )

    minutes, seconds = divmod(
        remainder,
        60
    )

    if days > 0:

        return (
            f"{days} ngày "
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{seconds:02d}"
        )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d}"
    )


# ============================================================
# 5. THÔNG TIN CẤP / MÓC
# ============================================================

def get_level_name(level):

    names = {

        0:
            "🆕 Cấp 0 — Từ mới",

        1:
            "🥉 Cấp 1 — Đang hình thành",

        2:
            "🥈 Cấp 2 — Đã nhớ",

        3:
            "🥇 Cấp 3 — Nhớ khá tốt",

        4:
            "💎 Cấp 4 — Nhớ lâu",

        5:
            "🏆 Cấp 5 — Ghi nhớ rất tốt",
    }

    return names.get(
        level,
        "🆕 Cấp 0 — Từ mới"
    )


def get_level_hooks(level):

    return LEVEL_HOOKS.get(
        level,
        []
    )


def get_hook_hours(item):

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

    if level <= 0:
        return 0

    hooks = get_level_hooks(level)

    if not hooks:
        return 0

    hook = max(
        1,
        min(
            hook,
            len(hooks)
        )
    )

    return hooks[hook - 1]


def get_current_interval(item):

    return get_hook_hours(item)


def get_progress_text(item):

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

    if level == 0:
        return "Cấp 0 • Từ mới"

    return f"Cấp {level} • Móc {hook}/4"


# ============================================================
# 6. CHUẨN HÓA ITEM CŨ
# ============================================================

def normalize_item(item):

    item = dict(item)

    try:
        item["id"] = int(
            item.get(
                "id",
                0
            )
        )

    except Exception:
        item["id"] = 0

    item["word"] = str(
        item.get(
            "word",
            ""
        )
    ).strip()

    item["phonetic"] = str(
        item.get(
            "phonetic",
            ""
        )
    ).strip()

    item["meaning"] = str(
        item.get(
            "meaning",
            ""
        )
    ).strip()

    item["example"] = str(
        item.get(
            "example",
            ""
        )
    ).strip()

    try:

        level = int(
            item.get(
                "level",
                0
            )
        )

    except Exception:

        level = 0

    level = max(
        0,
        min(
            MAX_LEVEL,
            level
        )
    )

    try:

        hook = int(
            item.get(
                "hook",
                0
            )
        )

    except Exception:

        hook = 0

    # ----------------------------------------
    # DỮ LIỆU CŨ CHỈ CÓ INTERVAL
    # ----------------------------------------

    if (
        "hook" not in item
        and level > 0
    ):

        try:

            old_interval = float(
                item.get(
                    "interval",
                    1
                )
            )

        except Exception:

            old_interval = 1

        best_level = 1
        best_hook = 1
        best_distance = float("inf")

        for lv, hooks in LEVEL_HOOKS.items():

            for hk, hours in enumerate(
                hooks,
                start=1
            ):

                distance = abs(
                    hours
                    - old_interval / 60
                )

                if distance < best_distance:

                    best_distance = distance
                    best_level = lv
                    best_hook = hk

        level = best_level
        hook = best_hook

    if level == 0:

        hook = 0

    else:

        hook = max(
            1,
            min(
                HOOKS_PER_LEVEL,
                hook
            )
        )

    item["level"] = level
    item["hook"] = hook

    try:

        item["review_count"] = int(
            item.get(
                "review_count",
                0
            )
        )

    except Exception:

        item["review_count"] = 0

    try:

        item["correct_count"] = int(
            item.get(
                "correct_count",
                0
            )
        )

    except Exception:

        item["correct_count"] = 0

    try:

        item["wrong_count"] = int(
            item.get(
                "wrong_count",
                0
            )
        )

    except Exception:

        item["wrong_count"] = 0

    item["last_response_time"] = item.get(
        "last_response_time",
        None
    )

    item["last_result"] = item.get(
        "last_result",
        None
    )

    # ----------------------------------------
    # NEXT REVIEW
    # ----------------------------------------

    next_review = item.get(
        "next_review"
    )

    if isinstance(
        next_review,
        datetime
    ):

        item["next_review"] = next_review

    elif isinstance(
        next_review,
        str
    ):

        try:

            item["next_review"] = (
                datetime.fromisoformat(
                    next_review
                )
            )

        except Exception:

            item["next_review"] = (
                datetime.now()
            )

    else:

        item["next_review"] = (
            datetime.now()
        )

    item["interval"] = (
        get_current_interval(item)
    )

    return item


# ============================================================
# 7. LOAD LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:

    saved_data = None

    try:

        saved_data = local_storage.getItem(
            "mochi_deck_data"
        )

    except Exception:

        saved_data = None

    if saved_data:

        try:

            items = json.loads(
                saved_data
            )

            if isinstance(
                items,
                list
            ):

                cleaned_items = []

                for raw_item in items:

                    if isinstance(
                        raw_item,
                        dict
                    ):

                        cleaned_items.append(
                            normalize_item(
                                raw_item
                            )
                        )

                st.session_state.deck = (
                    cleaned_items
                )

        except Exception:

            st.session_state.deck = []

    st.session_state.data_loaded = True


# ============================================================
# 8. SAVE LOCAL STORAGE
# ============================================================

def save_deck():

    serializable_deck = []

    for item in st.session_state.deck:

        copy_item = dict(item)

        if isinstance(
            copy_item.get(
                "next_review"
            ),
            datetime
        ):

            copy_item["next_review"] = (
                copy_item[
                    "next_review"
                ].isoformat()
            )

        serializable_deck.append(
            copy_item
        )

    try:

        local_storage.setItem(
            "mochi_deck_data",
            json.dumps(
                serializable_deck,
                ensure_ascii=False
            )
        )

    except Exception:

        pass


# ============================================================
# 9. ID
# ============================================================

def get_next_id():

    if not st.session_state.deck:
        return 1

    ids = []

    for item in st.session_state.deck:

        try:

            ids.append(
                int(
                    item.get(
                        "id",
                        0
                    )
                )
            )

        except Exception:

            pass

    if not ids:
        return 1

    return max(ids) + 1


# ============================================================
# 10. GOOGLE TRANSLATE
# ============================================================

def translate_single_text(text):

    """
    Anh -> Việt.

    Dùng Google Translate endpoint.
    Có timeout + xử lý lỗi.
    """

    if not text:
        return ""

    text = str(
        text
    ).strip()

    if not text:
        return ""

    try:

        encoded_text = urllib.parse.quote(
            text,
            safe=""
        )

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
            "?client=gtx"
            "&sl=en"
            "&tl=vi"
            "&dt=t"
            f"&q={encoded_text}"
        )

        request = urllib.request.Request(

            url,

            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept": (
                    "application/json,"
                    "text/plain,*/*"
                )
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            raw = response.read().decode(
                "utf-8"
            )

        data = json.loads(
            raw
        )

        if (
            isinstance(data, list)
            and len(data) > 0
            and isinstance(data[0], list)
        ):

            translated_parts = []

            for part in data[0]:

                if (
                    isinstance(part, list)
                    and len(part) >= 1
                    and part[0] is not None
                ):

                    translated_text = str(
                        part[0]
                    ).strip()

                    if translated_text:

                        translated_parts.append(
                            translated_text
                        )

            result = "".join(
                translated_parts
            ).strip()

            if result:
                return result

    except urllib.error.HTTPError as e:

        print(
            f"Google Translate HTTP Error: {e}"
        )

    except urllib.error.URLError as e:

        print(
            f"Google Translate URL Error: {e}"
        )

    except json.JSONDecodeError as e:

        print(
            f"Google Translate JSON Error: {e}"
        )

    except Exception as e:

        print(
            f"Google Translate Error: {e}"
        )

    return ""


# ============================================================
# 11. DICTIONARY API
# ============================================================

def fetch_dictionary_data(word):

    url = (
        "https://api.dictionaryapi.dev/"
        "api/v2/entries/en/"
        f"{urllib.parse.quote(word)}"
    )

    try:

        request = urllib.request.Request(

            url,

            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

            if (
                isinstance(data, list)
                and data
            ):

                return data

    except Exception as e:

        print(
            f"Dictionary API Error: {e}"
        )

    return None


def fetch_word_full_data(word):

    data = fetch_dictionary_data(
        word
    )

    if not data:

        return {
            "success": False
        }

    first = data[0]

    phonetic = (
        first.get(
            "phonetic",
            ""
        )
        or ""
    )

    if not phonetic:

        for phonetic_obj in first.get(
            "phonetics",
            []
        ):

            if phonetic_obj.get(
                "text"
            ):

                phonetic = (
                    phonetic_obj[
                        "text"
                    ]
                )

                break

    meanings = []
    examples = []

    for meaning_obj in first.get(
        "meanings",
        []
    ):

        part_of_speech = (
            meaning_obj.get(
                "partOfSpeech",
                ""
            )
        )

        for definition_obj in meaning_obj.get(
            "definitions",
            []
        ):

            definition = (
                definition_obj.get(
                    "definition",
                    ""
                )
            )

            example = (
                definition_obj.get(
                    "example",
                    ""
                )
            )

            if definition:

                meanings.append({

                    "type":
                        part_of_speech,

                    "definition":
                        definition
                })

            if example:

                examples.append(
                    example
                )

    # ========================================================
    # DỊCH TIẾNG VIỆT
    # ========================================================

    short_vn = translate_single_text(
        word
    )

    # ----------------------------------------
    # FALLBACK:
    # Nếu dịch từ không được,
    # thử dịch definition đầu tiên.
    # ----------------------------------------

    if not short_vn and meanings:

        short_vn = translate_single_text(
            meanings[0]["definition"]
        )

    if not short_vn:

        short_vn = (
            "Chưa lấy được "
            "bản dịch tiếng Việt"
        )

    return {

        "success": True,

        "phonetic":
            phonetic,

        "short_vn":
            short_vn,

        "meanings":
            meanings,

        "examples":
            examples,
    }


# ============================================================
# 12. LẤY VÍ DỤ ONLINE
# ============================================================

def fetch_online_example(word):

    data = fetch_dictionary_data(
        word
    )

    if not data:
        return None

    for meaning_obj in data[0].get(
        "meanings",
        []
    ):

        for definition_obj in meaning_obj.get(
            "definitions",
            []
        ):

            example = (
                definition_obj.get(
                    "example"
                )
            )

            if example:
                return example

    return None


# ============================================================
# 13. PHÁT ÂM
# ============================================================

def play_audio_script(word):

    safe_word = (
        word
        .replace(
            "\\",
            "\\\\"
        )
        .replace(
            "'",
            "\\'"
        )
        .replace(
            '"',
            '\\"'
        )
        .replace(
            "\n",
            " "
        )
        .replace(
            "\r",
            " "
        )
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
# 14. TẠO CÂU HỎI
# ============================================================

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

    st.session_state.q_type = (
        chosen_q
    )

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

    # ----------------------------------------
    # LẤY CÂU VÍ DỤ
    # ----------------------------------------

    if not example:

        online_example = (
            fetch_online_example(
                word
            )
        )

        if online_example:

            example = online_example

        else:

            example = (
                f"It is important "
                f"to understand "
                f"{word}."
            )

    deck_words = [

        x.get(
            "word",
            ""
        ).strip()

        for x in st.session_state.deck

        if (
            x.get(
                "word",
                ""
            ).strip()

            and

            x.get(
                "word",
                ""
            ).strip().lower()

            != word.lower()
        )
    ]

    deck_meanings = [

        x.get(
            "meaning",
            ""
        ).strip()

        for x in st.session_state.deck

        if (
            x.get(
                "meaning",
                ""
            ).strip()

            and

            x.get(
                "meaning",
                ""
            ).strip().lower()

            != meaning.lower()
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
                min(
                    len(deck_meanings),
                    3
                )
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
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

        random.shuffle(
            options
        )

        st.session_state.q_data = {

            "question":
                word,

            "options":
                options,

            "answer":
                meaning,
        }

    # ========================================================
    # 2. ĐIỀN TỪ
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        blank_sentence = re.sub(

            r"\b"
            + re.escape(word)
            + r"\b",

            "_____",

            example,

            flags=re.IGNORECASE
        )

        if blank_sentence == example:

            blank_sentence = (
                f"{example} _____"
            )

        st.session_state.q_data = {

            "sentence":
                blank_sentence,

            "answer":
                word,

            "word":
                word,
        }

    # ========================================================
    # 3. NGHĨA -> GÕ TỪ
    # ========================================================

    elif chosen_q == "SPELLING":

        st.session_state.q_data = {

            "question":
                meaning,

            "answer":
                word,
        }

    # ========================================================
    # 4. NGỮ CẢNH
    # ========================================================

    elif chosen_q == "CONTEXT_MATCH":

        options = [meaning]

        if deck_meanings:

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

            "Sự phát triển",

            "Khả năng thích nghi",

            "Thành tựu",

            "Môi trường",

            "Kinh nghiệm",
        ]

        for m in fallback_meanings:

            if len(options) >= 4:
                break

            if m not in options:
                options.append(m)

        random.shuffle(
            options
        )

        st.session_state.q_data = {

            "context":
                example,

            "word":
                word,

            "options":
                options,

            "answer":
                meaning,
        }

    # ========================================================
    # 5. ĐÚNG / SAI
    # ========================================================

    elif chosen_q == "FLASHCARD_TRUE_FALSE":

        is_true = random.choice(
            [True, False]
        )

        if is_true or not deck_meanings:

            display_meaning = meaning

            answer = True

        else:

            display_meaning = (
                random.choice(
                    deck_meanings
                )
            )

            answer = False

        st.session_state.q_data = {

            "word":
                word,

            "disp_meaning":
                display_meaning,

            "is_true":
                answer,

            "answer":
                answer,
        }

    # ========================================================
    # 6. NGHĨA -> CHỌN TỪ
    # ========================================================

    elif chosen_q == "MEANING_CHOICE":

        options = [word]

        if deck_words:

            sampled_words = random.sample(
                deck_words,
                min(
                    len(deck_words),
                    3
                )
            )

            for w in sampled_words:

                if (
                    w.lower()
                    not in [
                        x.lower()
                        for x in options
                    ]
                ):

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

            if (
                fb.lower()
                not in [
                    x.lower()
                    for x in options
                ]
            ):

                options.append(fb)

        random.shuffle(
            options
        )

        st.session_state.q_data = {

            "word":
                word,

            "question":
                meaning,

            "options":
                options,

            "answer":
                word,
        }


# ============================================================
# 15. XỬ LÝ QUÁ HẠN
# ============================================================

def apply_overdue_penalty(item):

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

    if level <= 0:
        return False

    changed = False

    if hook <= 1:

        if level == 1:

            hook = 1
            changed = True

        else:

            level -= 1
            hook = 4
            changed = True

    else:

        hook -= 1
        changed = True

    item["level"] = level
    item["hook"] = hook

    item["interval"] = (
        get_current_interval(item)
    )

    item["next_review"] = (
        datetime.now()
    )

    return changed


def process_overdue_items():

    now = datetime.now()

    changed = False

    for item in st.session_state.deck:

        if item.get(
            "level",
            0
        ) <= 0:

            continue

        next_review = item.get(
            "next_review"
        )

        if not isinstance(
            next_review,
            datetime
        ):

            continue

        if next_review <= now:

            if not item.get(
                "_overdue_processed",
                False
            ):

                changed_now = (
                    apply_overdue_penalty(
                        item
                    )
                )

                item[
                    "_overdue_processed"
                ] = True

                if changed_now:
                    changed = True

    if changed:
        save_deck()


# ============================================================
# 16. CHUYỂN SANG MÓC TIẾP THEO
# ============================================================

def advance_after_correct(item):

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

    if level == 0:

        level = 1
        hook = 1

    elif level < MAX_LEVEL:

        if hook < 4:

            hook += 1

        else:

            level += 1
            hook = 1

    else:

        if hook < 4:

            hook += 1

        else:

            level = 5
            hook = 4

    item["level"] = level
    item["hook"] = hook

    item["interval"] = (
        get_current_interval(item)
    )


# ============================================================
# 17. LÙI MÓC KHI SAI
# ============================================================

def move_back_after_wrong(item):

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

    if level == 0:

        level = 0
        hook = 0

    elif level == 1:

        if hook <= 1:

            level = 1
            hook = 1

        else:

            hook -= 1

    else:

        if hook > 1:

            hook -= 1

        else:

            level -= 1
            hook = 4

            if level < 1:

                level = 1
                hook = 1

    item["level"] = level
    item["hook"] = hook

    item["interval"] = (
        get_current_interval(item)
    )


# ============================================================
# 18. XỬ LÝ ĐÁP ÁN
# ============================================================

def process_answer(
    is_correct,
    correct_ans_text
):

    item = (
        st.session_state.review_item
    )

    if item is None:
        return

    response_time = max(

        0.1,

        time.time()
        - st.session_state.review_start_time
    )

    old_level = int(
        item.get(
            "level",
            0
        )
    )

    old_hook = int(
        item.get(
            "hook",
            0
        )
    )

    if is_correct:

        item["review_count"] = (
            int(
                item.get(
                    "review_count",
                    0
                )
            )
            + 1
        )

        item["correct_count"] = (
            int(
                item.get(
                    "correct_count",
                    0
                )
            )
            + 1
        )

        item["last_result"] = (
            "correct"
        )

        advance_after_correct(
            item
        )

    else:

        item["review_count"] = (
            int(
                item.get(
                    "review_count",
                    0
                )
            )
            + 1
        )

        item["wrong_count"] = (
            int(
                item.get(
                    "wrong_count",
                    0
                )
            )
            + 1
        )

        item["last_result"] = (
            "wrong"
        )

        move_back_after_wrong(
            item
        )

    item["last_response_time"] = round(
        response_time,
        2
    )

    new_interval_hours = (
        get_current_interval(item)
    )

    if new_interval_hours <= 0:

        item["next_review"] = (
            datetime.now()
        )

    else:

        item["next_review"] = (

            datetime.now()
            + timedelta(
                hours=new_interval_hours
            )
        )

    item["_overdue_processed"] = False

    item["interval"] = (
        new_interval_hours
    )

    # ----------------------------------------
    # THÔNG BÁO
    # ----------------------------------------

    if is_correct:

        st.success(
            "✨ Chính xác!"
        )

        st.write(
            "⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        st.success(

            f"📈 Cấp {old_level}, "
            f"móc {old_hook}/4"
            f" → "
            f"Cấp {item['level']}, "
            f"móc {item['hook']}/4"
        )

        if new_interval_hours > 0:

            st.info(
                "⏰ Móc tiếp theo: "
                f"**{format_hours(new_interval_hours)}**"
            )

        if old_level < item["level"]:

            st.balloons()

            st.success(
                f"🎉 Đã lên "
                f"Cấp {item['level']}!"
            )

        if (
            item["level"] == 5
            and item["hook"] == 4
        ):

            st.success(
                "🏆 Từ này đã đạt "
                "Cấp 5 — Móc 4!"
            )

    else:

        st.error(
            "❌ Chưa chính xác."
        )

        st.warning(
            "Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        st.warning(

            f"📉 Cấp {old_level}, "
            f"móc {old_hook}/4"
            f" → "
            f"Cấp {item['level']}, "
            f"móc {item['hook']}/4"
        )

        if new_interval_hours > 0:

            st.info(
                "🔄 Móc mới: "
                f"**{format_hours(new_interval_hours)}**"
            )

        else:

            st.info(
                "🆕 Từ này vẫn ở Cấp 0."
            )

    save_deck()

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}
    st.session_state.review_start_time = 0

    time.sleep(0.8)

    st.rerun()


# ============================================================
# 19. RESET ALL
# ============================================================

def reset_all_to_level_zero():

    for item in st.session_state.deck:

        item["level"] = 0
        item["hook"] = 0
        item["interval"] = 0

        item["next_review"] = (
            datetime.now()
        )

        item["review_count"] = 0
        item["correct_count"] = 0
        item["wrong_count"] = 0

        item["last_response_time"] = None
        item["last_result"] = None

        item["_overdue_processed"] = False

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}
    st.session_state.review_started = False

    save_deck()


# ============================================================
# 20. XỬ LÝ QUÁ HẠN
# ============================================================

process_overdue_items()


# ============================================================
# 21. HEADER
# ============================================================

st.title(
    "🍌 MochiVocab"
)

st.caption(
    "Dynamic Golden Time • "
    "Học theo cấp và 4 móc ghi nhớ"
)

now = datetime.now()

due_count = sum(

    1

    for x in st.session_state.deck

    if (
        x.get("next_review")
        and x["next_review"] <= now
    )
)

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

    label_visibility="collapsed"
)

st.markdown("---")


# ============================================================
# 22. TAB ÔN TẬP
# ============================================================

if selected_tab == "⏰ Ôn Tập":

    st.subheader(
        "⏰ Ôn tập đúng Thời Điểm Vàng"
    )

    now = datetime.now()

    due_items = [

        x

        for x in st.session_state.deck

        if (
            x.get("next_review")
            and x["next_review"] <= now
        )
    ]

    # ----------------------------------------
    # KHÔNG CÓ TỪ
    # ----------------------------------------

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang "
            "**🔍 Tra Từ Mới** "
            "để thêm từ."
        )

    # ----------------------------------------
    # CHƯA ĐẾN GIỜ
    # ----------------------------------------

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
            "🎉 Hiện tại không có từ "
            "nào đến Thời Điểm Vàng."
        )

        col1, col2 = st.columns(2)

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

        st.info(
            "⏰ Còn khoảng "
            f"**{format_remaining(remaining)}**"
        )

        st.markdown(

            f"""
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

                <div style="
                    font-size:30px;
                    font-weight:bold;
                    font-family:monospace;
                ">
                    {format_remaining(remaining)}
                </div>

            </div>
            """,

            unsafe_allow_html=True
        )

    # ----------------------------------------
    # CÓ TỪ CẦN ÔN
    # ----------------------------------------

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

                MochiVocab sẽ chọn một từ đang
                đến giờ và bắt đầu tính thời gian
                phản hồi.
                """
            )

            if st.button(

                "▶️ BẮT ĐẦU ÔN TẬP",

                type="primary",

                use_container_width=True,

                key="start_review"
            ):

                min_level = min(

                    x.get(
                        "level",
                        0
                    )

                    for x in due_items
                )

                candidates = [

                    x

                    for x in due_items

                    if x.get(
                        "level",
                        0
                    ) == min_level
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

                min_level = min(

                    x.get(
                        "level",
                        0
                    )

                    for x in due_items
                )

                candidates = [

                    x

                    for x in due_items

                    if x.get(
                        "level",
                        0
                    ) == min_level
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

            # ----------------------------------------
            # DỪNG
            # ----------------------------------------

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

            # ----------------------------------------
            # THÔNG TIN TỪ
            # ----------------------------------------

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

            progress = (

                hook / 4

                if level > 0

                else 0
            )

            st.progress(
                progress
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(
                        level
                    )
                )

            with col2:

                st.caption(

                    f"Móc: {hook}/4"

                    if level > 0

                    else
                    "Móc: 0/4"
                )

            if level == 0:

                st.caption(
                    "⏰ Khoảng ôn: "
                    "**0 giờ — Từ mới**"
                )

            else:

                current_hours = (
                    get_current_interval(
                        item
                    )
                )

                st.caption(
                    "📐 Móc hiện tại: "
                    f"**{format_hours(current_hours)}**"
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
                        )
                    ):

                        process_answer(

                            option.strip().lower()
                            ==
                            item[
                                "meaning"
                            ].strip().lower(),

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
                    f"**{q_data.get('sentence', '')}**"
                )

                st.caption(
                    "Điền từ tiếng Anh còn thiếu."
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
                    )
                ):

                    process_answer(

                        user_ans.strip().lower()
                        ==
                        item["word"].strip().lower(),

                        item["word"].upper()
                    )

            # =================================================
            # CÂU 3
            # =================================================

            elif q_type == "SPELLING":

                st.markdown(
                    "### ✍️ LUYỆN CHÍNH TẢ"
                )

                st.info(
                    "Nghĩa tiếng Việt: "
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
                    )
                ):

                    process_answer(

                        user_ans.strip().lower()
                        ==
                        item["word"].strip().lower(),

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
                    f'"{q_data.get("context", "")}"'
                )

                st.write(

                    f'Từ '
                    f'**{item["word"].upper()}** '
                    f'có nghĩa là gì?'
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
                        )
                    ):

                        process_answer(

                            option.strip().lower()
                            ==
                            item[
                                "meaning"
                            ].strip().lower(),

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
                        )
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
                        )
                    ):

                        process_answer(

                            not q_data["is_true"],

                            "SAI"
                            if not q_data["is_true"]
                            else "ĐÚNG"
                        )

            # =================================================
            # CÂU 6
            # =================================================

            elif q_type == "MEANING_CHOICE":

                st.markdown(
                    "### 🔤 NGHĨA → CHỌN TỪ TIẾNG ANH"
                )

                st.info(

                    "Nghĩa: "
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
                        )
                    ):

                        process_answer(

                            option.strip().lower()
                            ==
                            item[
                                "word"
                            ].strip().lower(),

                            item["word"].upper()
                        )


# ============================================================
# 23. TAB TRA TỪ MỚI
# ============================================================

elif selected_tab == "🔍 Tra Từ Mới":

    st.subheader(
        "🔍 Tra cứu & Thêm từ mới"
    )

    word_input = st.text_input(

        "Nhập từ tiếng Anh:",

        placeholder=(
            "Ví dụ: resilience, "
            "innovate, discuss..."
        )
    ).strip().lower()

    if st.button(

        "🔎 Tra Từ",

        type="primary"
    ):

        if word_input:

            with st.spinner(
                "Đang tra từ..."
            ):

                data = (
                    fetch_word_full_data(
                        word_input
                    )
                )

            if not data.get(
                "success",
                False
            ):

                st.error(

                    f"❌ Không tìm thấy "
                    f"**{word_input}**."
                )

                st.session_state.temp_word = None

            else:

                examples = data.get(
                    "examples",
                    []
                )

                if examples:

                    example = examples[0]

                else:

                    example = (

                        f"It is important "
                        f"to understand "
                        f"{word_input}."
                    )

                st.session_state.temp_word = {

                    "word":
                        word_input,

                    "phonetic":
                        data.get(
                            "phonetic",
                            ""
                        ),

                    "meaning":
                        data.get(
                            "short_vn",
                            ""
                        ),

                    "example":
                        example,
                }

    data = st.session_state.get(
        "temp_word"
    )

    if (

        data is not None

        and isinstance(
            data,
            dict
        )

        and data.get(
            "word",
            ""
        ) == word_input
    ):

        st.markdown("---")

        st.info(

            f"**{data.get('word', '').upper()}** "
            f"`{data.get('phonetic', '')}`"
        )

        st.write(

            "👉 **Nghĩa tiếng Việt:** "
            f"{data.get('meaning', '')}"
        )

        st.caption(

            "💡 Ví dụ: "
            f"{data.get('example', '')}"
        )

        col1, col2 = st.columns(2)

        with col1:

            if st.button(

                "🔊 Nghe",

                key="new_word_audio"
            ):

                play_audio_script(
                    data["word"]
                )

        with col2:

            if st.button(

                "➕ Thêm vào Sổ Tay",

                key="add_new_word"
            ):

                exists = any(

                    x.get(
                        "word",
                        ""
                    ).strip().lower()

                    ==
                    data[
                        "word"
                    ].strip().lower()

                    for x in
                    st.session_state.deck
                )

                if exists:

                    st.warning(

                        "⚠️ Từ này đã có "
                        "trong Sổ Tay."
                    )

                else:

                    new_item = {

                        "id":
                            get_next_id(),

                        "word":
                            data["word"],

                        "phonetic":
                            data.get(
                                "phonetic",
                                ""
                            ),

                        "meaning":
                            data.get(
                                "meaning",
                                ""
                            ),

                        "example":
                            data.get(
                                "example",
                                ""
                            ),

                        "level":
                            0,

                        "hook":
                            0,

                        "interval":
                            0,

                        "review_count":
                            0,

                        "correct_count":
                            0,

                        "wrong_count":
                            0,

                        "last_response_time":
                            None,

                        "last_result":
                            None,

                        "next_review":
                            datetime.now(),

                        "_overdue_processed":
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

                        "🆕 Từ mới bắt đầu "
                        "**Cấp 0 — 0 giờ**."
                    )

                    time.sleep(
                        0.5
                    )

                    st.rerun()


# ============================================================
# 24. TAB SỔ TAY
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

            if (
                x.get("next_review")
                and
                x["next_review"]
                <= datetime.now()
            )
        )

        mastered = sum(

            1

            for x in st.session_state.deck

            if (
                x.get("level", 0)
                == 5

                and

                x.get("hook", 0)
                == 4
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
                "Cấp 5 • Móc 4",
                mastered
            )

        st.markdown("---")

        table_data = []

        for item in st.session_state.deck:

            next_review = item.get(
                "next_review"
            )

            if isinstance(
                next_review,
                datetime
            ):

                remaining = (

                    next_review
                    - datetime.now()
                ).total_seconds()

            else:

                remaining = 0

            if remaining <= 0:

                status = (
                    "🔥 Sẵn sàng ôn!"
                )

            else:

                status = (

                    f"⏳ "
                    f"{format_remaining(remaining)}"
                )

            correct_count = int(
                item.get(
                    "correct_count",
                    0
                )
            )

            wrong_count = int(
                item.get(
                    "wrong_count",
                    0
                )
            )

            accuracy_total = (
                correct_count
                + wrong_count
            )

            if accuracy_total > 0:

                accuracy_text = (

                    f"{correct_count / accuracy_total * 100:.0f}%"
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

            if level == 0:

                hook_text = "Cấp 0"

                interval_text = "0 giờ"

            else:

                hook_text = (

                    f"Cấp {level} • "
                    f"Móc {hook}/4"
                )

                interval_text = (

                    format_hours(

                        get_current_interval(
                            item
                        )
                    )
                )

            table_data.append({

                "Từ":
                    item.get(
                        "word",
                        ""
                    ).upper(),

                "Nghĩa":
                    item.get(
                        "meaning",
                        ""
                    ),

                "Cấp":
                    hook_text,

                "Trạng thái":
                    get_level_name(
                        level
                    ),

                "Móc":
                    interval_text,

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

        # ----------------------------------------
        # HỆ THỐNG MÓC
        # ----------------------------------------

        st.markdown(
            "### 📐 Hệ thống Thời Điểm Vàng"
        )

        hook_table = {

            "Cấp 0":
                "0h — Từ mới",

            "Cấp 1":
                "1h → 4h → 12h → 24h",

            "Cấp 2":
                "25h → 28h → 36h → 48h",

            "Cấp 3":
                "49h → 52h → 60h → 72h",

            "Cấp 4":
                "73h → 76h → 84h → 96h",

            "Cấp 5":
                "97h → 100h → 108h → 120h",
        }

        st.table(

            [

                {
                    "Cấp":
                        level_name,

                    "Các móc":
                        hooks
                }

                for level_name, hooks

                in hook_table.items()
            ]
        )

        st.caption(

            "💡 Đúng: tiến 1 móc. "
            "Sai: lùi 1 móc. "
            "Móc 1 Cấp 1 sai vẫn ở Cấp 1."
        )

        st.markdown("---")

        # ----------------------------------------
        # RESET ALL
        # ----------------------------------------

        st.markdown(
            "### 🔄 Đặt lại toàn bộ"
        )

        st.warning(

            "Thao tác này sẽ đưa tất cả từ "
            "về **Cấp 0 — 0 giờ** và xóa "
            "toàn bộ lịch sử ôn tập."
        )

        if st.button(

            "🔄 RESET ALL VỀ CẤP 0",

            type="secondary",

            use_container_width=True,

            key="reset_all_words"
        ):

            reset_all_to_level_zero()

            st.success(

                "✅ Đã reset toàn bộ từ "
                "về Cấp 0."
            )

            time.sleep(
                0.5
            )

            st.rerun()

        st.markdown("---")

        # ----------------------------------------
        # DELETE ALL
        # ----------------------------------------

        if st.button(

            "🗑️ Xóa toàn bộ từ vựng",

            key="delete_all_words"
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

            time.sleep(
                0.5
            )

            st.rerun()

    else:

        st.info(
            "📚 Sổ tay đang trống."
        )


# ============================================================
# 25. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • Dynamic Golden Time"
)
