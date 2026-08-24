import json
import random
import time
import urllib.parse
import urllib.request
import requests
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
# 2. HỆ THỐNG GOLDEN TIME
#
# Mỗi cấp có 4 MÓC.
#
# Cấp 0:
#   Móc 1: 1h
#   Móc 2: 4h
#   Móc 3: 12h
#   Móc 4: 24h
#
# Cấp 1:
#   25h -> 28h -> 36h -> 48h
#
# Cấp 2:
#   49h -> 52h -> 60h -> 72h
#
# Cấp 3:
#   73h -> 76h -> 84h -> 96h
#
# Cấp 4:
#   97h -> 100h -> 108h -> 120h
#
# Hoàn thành móc 4 của cấp 4
# => lên Cấp 5 (Mastered)
# ============================================================

GOLDEN_SCHEDULE = {
    0: [1, 4, 12, 24],
    1: [25, 28, 36, 48],
    2: [49, 52, 60, 72],
    3: [73, 76, 84, 96],
    4: [97, 100, 108, 120],
}

MAX_LEVEL = 5
HOOKS_PER_LEVEL = 4


# ============================================================
# 3. SESSION STATE
# ============================================================

if "deck" not in st.session_state:
    st.session_state.deck = []

if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

if "review_item" not in st.session_state:
    st.session_state.review_item = None

if "q_type" not in st.session_state:
    st.session_state.q_type = None

if "q_data" not in st.session_state:
    st.session_state.q_data = {}

if "review_start_time" not in st.session_state:
    st.session_state.review_start_time = 0

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "⏰ Ôn Tập"

if "temp_word" not in st.session_state:
    st.session_state.temp_word = None

if "review_started" not in st.session_state:
    st.session_state.review_started = False


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
# 5. GOLDEN TIME HELPERS
# ============================================================

def get_current_hook(item):
    """
    hook:
        0 = chưa qua móc nào
        1 = đang ở móc 1
        2 = đang ở móc 2
        3 = đang ở móc 3
        4 = vừa hoàn thành móc 4

    Trong thực tế item["hook"] lưu 0..3,
    nghĩa là móc hiện tại tiếp theo.
    """

    level = int(item.get("level", 0))

    if level >= MAX_LEVEL:
        return 4

    hook = int(item.get("hook", 0))
    return max(0, min(3, hook))


def get_current_interval_hours(item):
    level = int(item.get("level", 0))

    if level >= MAX_LEVEL:
        return 120

    hook = get_current_hook(item)

    return GOLDEN_SCHEDULE[level][hook]


def get_current_interval_minutes(item):
    return get_current_interval_hours(item) * 60


def get_next_interval_after_correct(item):
    """
    Tính móc tiếp theo sau khi trả lời đúng.

    Ví dụ:

    level 0, hook 0
        1h -> đúng -> hook 1 => 4h

    level 0, hook 1
        4h -> đúng -> hook 2 => 12h

    level 0, hook 3
        24h -> đúng -> level 1, hook 0 => 25h
    """

    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

    if level >= MAX_LEVEL:
        return 120

    if hook < 3:
        return GOLDEN_SCHEDULE[level][hook + 1]

    # Đã hoàn thành móc 4
    if level < 4:
        return GOLDEN_SCHEDULE[level + 1][0]

    # Cấp 4 móc 4 => Mastered cấp 5
    return 120


def advance_after_correct(item):
    """
    Trả lời đúng 1 lần:
    - Nếu chưa phải móc 4 => tăng 1 móc.
    - Nếu hoàn thành móc 4 => lên 1 cấp.
    """

    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

    if level >= MAX_LEVEL:
        item["level"] = MAX_LEVEL
        item["hook"] = 3
        item["interval"] = 120 * 60
        return

    if hook < 3:
        item["hook"] = hook + 1
        item["interval"] = GOLDEN_SCHEDULE[level][hook + 1] * 60

    else:
        if level < 4:
            item["level"] = level + 1
            item["hook"] = 0
            item["interval"] = GOLDEN_SCHEDULE[level + 1][0] * 60
        else:
            item["level"] = MAX_LEVEL
            item["hook"] = 3
            item["interval"] = 120 * 60


def drop_after_wrong(item):
    """
    Trả lời sai:
    - Rớt đúng 1 móc.
    - Nếu đang ở móc 2 => về móc 1.
    - Nếu đang ở móc 1 => về móc 0.
    - Nếu đang ở móc 0 của cấp hiện tại => tụt 1 cấp
      và quay về móc 4 của cấp trước.

    Ví dụ:

    Cấp 2 móc 3
        sai
        => Cấp 2 móc 2

    Cấp 2 móc 1
        sai
        => Cấp 2 móc 0

    Cấp 2 móc 0
        sai
        => Cấp 1 móc 3
    """

    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

    if level >= MAX_LEVEL:
        # Cấp 5 bị sai => quay về Cấp 4, móc 4
        item["level"] = 4
        item["hook"] = 3
        item["interval"] = GOLDEN_SCHEDULE[4][3] * 60
        return

    if hook > 0:
        item["hook"] = hook - 1
        item["interval"] = GOLDEN_SCHEDULE[level][hook - 1] * 60

    else:
        if level > 0:
            item["level"] = level - 1
            item["hook"] = 3
            item["interval"] = GOLDEN_SCHEDULE[level - 1][3] * 60
        else:
            item["level"] = 0
            item["hook"] = 0
            item["interval"] = GOLDEN_SCHEDULE[0][0] * 60


def get_level_name(level):
    names = {
        0: "🆕 Cấp 0 — Mới học",
        1: "🥉 Cấp 1 — Đang hình thành",
        2: "🥈 Cấp 2 — Đã nhớ",
        3: "🥇 Cấp 3 — Nhớ khá tốt",
        4: "💎 Cấp 4 — Nhớ lâu",
        5: "🏆 Cấp 5 — Ghi nhớ rất tốt",
    }

    return names.get(level, "🆕 Cấp 0")


def get_hook_name(hook):
    names = {
        0: "Móc 1/4",
        1: "Móc 2/4",
        2: "Móc 3/4",
        3: "Móc 4/4",
    }

    return names.get(hook, "Móc 1/4")


def get_progress_value(item):
    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

    if level >= MAX_LEVEL:
        return 1.0

    total_steps = 5 * 4
    current_step = level * 4 + hook

    return min(1.0, current_step / total_steps)


# ============================================================
# 6. LOAD LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:

    saved_data = local_storage.getItem("mochi_deck_data")

    if saved_data:

        try:
            items = json.loads(saved_data)
            cleaned_items = []

            for item in items:

                # --------------------------------------------
                # Tương thích dữ liệu cũ
                # --------------------------------------------

                item["level"] = max(
                    0,
                    min(
                        MAX_LEVEL,
                        int(item.get("level", 0))
                    )
                )

                if "hook" not in item:

                    # Dữ liệu cũ không có hook.
                    # Cho về móc đầu của cấp hiện tại.
                    item["hook"] = 0

                item["hook"] = max(
                    0,
                    min(3, int(item.get("hook", 0)))
                )

                if "next_review" not in item:
                    item["next_review"] = datetime.now()

                if isinstance(item["next_review"], str):

                    try:
                        item["next_review"] = datetime.fromisoformat(
                            item["next_review"]
                        )
                    except Exception:
                        item["next_review"] = datetime.now()

                if "interval" not in item:
                    item["interval"] = (
                        get_current_interval_minutes(item)
                    )

                item["review_count"] = int(
                    item.get("review_count", 0)
                )

                item["correct_count"] = int(
                    item.get("correct_count", 0)
                )

                item["wrong_count"] = int(
                    item.get("wrong_count", 0)
                )

                item["last_response_time"] = item.get(
                    "last_response_time",
                    None
                )

                item["last_result"] = item.get(
                    "last_result",
                    None
                )

                cleaned_items.append(item)

            st.session_state.deck = cleaned_items

        except Exception:
            st.session_state.deck = []

    st.session_state.data_loaded = True


def save_deck():

    serializable_deck = []

    for item in st.session_state.deck:

        copy_item = item.copy()

        if isinstance(copy_item.get("next_review"), datetime):
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
# 7. PHÁT ÂM
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
# 8. DỊCH ANH -> VIỆT
# ============================================================

def is_probably_vietnamese(text):
    """
    Kiểm tra sơ bộ xem kết quả có dấu tiếng Việt hay không.
    """

    if not text:
        return False

    vietnamese_chars = (
        "ăâđêôơư"
        "áàảãạ"
        "ấầẩẫậ"
        "ắằẳẵặ"
        "éèẻẽẹ"
        "ếềểễệ"
        "íìỉĩị"
        "óòỏõọ"
        "ốồổỗộ"
        "ớờởỡợ"
        "úùủũụ"
        "ứừửữự"
        "ýỳỷỹỵ"
    )

    text_lower = text.lower()

    return any(
        char in text_lower
        for char in vietnamese_chars
    )


def translate_google(text):

    if not text or not text.strip():
        return None

    try:

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
            "?client=gtx"
            "&sl=en"
            "&tl=vi"
            "&dt=t"
            "&q="
            + urllib.parse.quote(text.strip())
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

            if (
                isinstance(data, list)
                and len(data) > 0
                and isinstance(data[0], list)
            ):

                translated = "".join(
                    part[0]
                    for part in data[0]
                    if part and part[0]
                ).strip()

                if translated:
                    return translated

    except Exception:
        pass

    return None


def translate_mymemory(text):

    if not text or not text.strip():
        return None

    try:

        url = (
            "https://api.mymemory.translated.net/get"
            "?q="
            + urllib.parse.quote(text.strip())
            + "&langpair=en|vi"
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

    return None


def translate_single_text(text):

    if not text or not text.strip():
        return ""

    original = text.strip()

    # --------------------------------------------
    # Google Translate
    # --------------------------------------------

    translated = translate_google(original)

    if translated:
        # Nếu không giống hệt tiếng Anh ban đầu
        # thì chấp nhận.
        if translated.lower() != original.lower():
            return translated

        # Một số trường hợp Google trả nguyên text.
        # Chỉ chấp nhận nếu có dấu tiếng Việt.
        if is_probably_vietnamese(translated):
            return translated

    # --------------------------------------------
    # MyMemory fallback
    # --------------------------------------------

    translated = translate_mymemory(original)

    if translated:
        if translated.lower() != original.lower():
            return translated

        if is_probably_vietnamese(translated):
            return translated

    # --------------------------------------------
    # Không được phép trả lại tiếng Anh
    # --------------------------------------------

    return ""


# ============================================================
# 9. TRA TỪ ONLINE
# ============================================================

def fetch_word_full_data_FAST(word):

    url = (
        "https://api.dictionaryapi.dev/api/v2/"
        "entries/en/"
        + urllib.parse.quote(word)
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

                # ----------------------------------------
                # Nếu phonetic nằm trong phonetics[]
                # ----------------------------------------

                if phonetic == f"/{word}/":

                    for p in first.get(
                        "phonetics",
                        []
                    ):

                        if p.get("text"):
                            phonetic = p["text"]
                            break

                # ----------------------------------------
                # Definitions + examples
                # ----------------------------------------

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
                            definition.get(
                                "definition"
                            )
                        )

                        if definition_text:

                            meanings_raw.append({
                                "type": pos,
                                "en": definition_text
                            })

                        example = definition.get(
                            "example"
                        )

                        if example:
                            examples.append(example)

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

    # ========================================================
    # DỊCH NGHĨA EN -> VI
    # ========================================================

    # Dịch definition tiếng Anh thay vì dịch riêng
    # mỗi từ.
    #
    # Ví dụ:
    #
    # resilience
    # English definition:
    # "the ability of people or things to recover..."
    #
    # => tiếng Việt sẽ tốt hơn nhiều.
    # ========================================================

    vietnamese_meanings = []

    for meaning_obj in meanings_raw[:3]:

        en_definition = meaning_obj["en"]

        vn_definition = translate_single_text(
            en_definition
        )

        if vn_definition:

            vietnamese_meanings.append(
                f"({meaning_obj['type']}) {vn_definition}"
            )

    # --------------------------------------------
    # Nếu không dịch được definition
    # thì thử dịch chính từ
    # --------------------------------------------

    if not vietnamese_meanings:

        translated_word = translate_single_text(
            word
        )

        if translated_word:
            vietnamese_meanings = [
                translated_word
            ]

    if not vietnamese_meanings:

        return {
            "success": False,
            "translation_error": True
        }

    return {
        "success": True,
        "phonetic": phonetic,
        "short_vn": "; ".join(
            vietnamese_meanings
        ),
        "examples": examples
    }


# ============================================================
# 10. LẤY EXAMPLE
# ============================================================

def fetch_online_word_data(word):

    try:

        url = (
            "https://api.dictionaryapi.dev/api/v2/"
            "entries/en/"
            + urllib.parse.quote(word)
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
        ) as res:

            data = json.loads(
                res.read().decode("utf-8")
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
# 11. OXFORD LINK
# ============================================================

def get_oxford_url(word):

    return (
        "https://www.oxfordlearnersdictionaries.com/"
        "definition/english/"
        + urllib.parse.quote(
            word.strip().lower()
        )
    )


# ============================================================
# 12. ID
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
# 13. XỬ LÝ ĐÁP ÁN
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

    old_interval = get_current_interval_minutes(
        item
    )

    item["review_count"] = int(
        item.get("review_count", 0)
    ) + 1

    item["last_response_time"] = round(
        response_time,
        2
    )

    if is_correct:

        item["correct_count"] = int(
            item.get("correct_count", 0)
        ) + 1

        item["last_result"] = "correct"

        # ----------------------------------------
        # Tăng móc / tăng cấp
        # ----------------------------------------

        advance_after_correct(item)

        new_level = int(
            item.get("level", 0)
        )

        new_hook = int(
            item.get("hook", 0)
        )

        new_interval_hours = (
            get_current_interval_hours(item)
        )

        item["next_review"] = (
            datetime.now()
            + timedelta(
                hours=new_interval_hours
            )
        )

        item["interval"] = (
            new_interval_hours * 60
        )

        st.success(
            "✨ Chính xác!"
        )

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        if new_level > old_level:

            st.success(
                f"📈 Lên cấp: "
                f"**Cấp {old_level} → Cấp {new_level}**"
            )

            st.success(
                f"🎯 Bắt đầu móc 1/4 của Cấp {new_level}"
            )

        else:

            st.success(
                f"🎯 Móc: "
                f"**{old_hook + 1}/4 → {new_hook + 1}/4**"
            )

        st.info(
            f"⏰ Thời Điểm Vàng tiếp theo: "
            f"**{format_interval(item['interval'])}**"
        )

        if new_level == MAX_LEVEL:

            st.balloons()

            st.success(
                "🏆 Từ này đã đạt Cấp 5 — "
                "Ghi nhớ rất tốt!"
            )

    else:

        item["wrong_count"] = int(
            item.get("wrong_count", 0)
        ) + 1

        item["last_result"] = "wrong"

        # ----------------------------------------
        # Rớt 1 móc
        # ----------------------------------------

        drop_after_wrong(item)

        new_level = int(
            item.get("level", 0)
        )

        new_hook = int(
            item.get("hook", 0)
        )

        new_interval_hours = (
            get_current_interval_hours(item)
        )

        # Sai thì câu hỏi mới sẽ được tạo lại.
        # Đặt next_review = NOW để từ này
        # xuất hiện lại ngay sau rerun.
        item["next_review"] = datetime.now()

        item["interval"] = (
            new_interval_hours * 60
        )

        st.error(
            "❌ Chưa chính xác."
        )

        st.warning(
            f"Đáp án đúng: **{correct_ans_text}**"
        )

        st.warning(
            f"📉 Rớt 1 móc: "
            f"Cấp {old_level} / Móc {old_hook + 1}"
            f" → "
            f"Cấp {new_level} / Móc {new_hook + 1}"
        )

        st.info(
            f"🔄 Từ này sẽ được tạo **câu hỏi mới ngay**."
        )

        st.info(
            f"⏰ Mốc hiện tại: "
            f"**{format_interval(item['interval'])}**"
        )

    save_deck()

    # --------------------------------------------
    # Xóa câu hỏi hiện tại
    # --------------------------------------------

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    time.sleep(0.8)

    st.rerun()


# ============================================================
# 14. TẠO CÂU HỎI
#
# BỎ AUDIO_CHOICE
#
# Còn 6 dạng:
#
# 1. CHOICE_MEANING
# 2. FILL_BLANK
# 3. SPELLING
# 4. CONTEXT_MATCH
# 5. FLASHCARD_TRUE_FALSE
# 6. MEANING_CHOICE
# ============================================================

def prepare_review_question(item):

    q_types = [
        "CHOICE_MEANING",
        "FILL_BLANK",
        "SPELLING",
        "CONTEXT_MATCH",
        "FLASHCARD_TRUE_FALSE",
        "MEANING_CHOICE"
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

    # --------------------------------------------
    # Nếu chưa có example thì lấy online
    # --------------------------------------------

    if not example:

        online_example = (
            fetch_online_word_data(word)
        )

        if online_example:
            example = online_example
            item["example"] = example

        else:
            example = (
                f"The word '{word}' is "
                f"important to understand."
            )

    # --------------------------------------------
    # Words khác
    # --------------------------------------------

    deck_words = [
        x.get("word", "").strip()
        for x in st.session_state.get(
            "deck",
            []
        )
        if (
            x.get("word", "").strip()
            and x.get("word", "").strip().lower()
            != word.lower()
        )
    ]

    deck_meanings = [
        x.get("meaning", "").strip()
        for x in st.session_state.get(
            "deck",
            []
        )
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
            "Sự kiên trì",
            "Cải thiện",
            "Thách thức"
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
            "answer": meaning
        }

    # ========================================================
    # 2. CÂU -> ĐIỀN TỪ
    #
    # Example lấy từ dictionary.
    # Có link mở Oxford để xem chính từ đó.
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        # Tìm chính xác từ trong câu.
        pattern = re.compile(
            r"\b"
            + re.escape(word)
            + r"\b",
            re.IGNORECASE
        )

        blank_sentence = pattern.sub(
            "_____",
            example
        )

        # Nếu example không chứa word
        if blank_sentence == example:

            # Thử dạng mềm hơn
            blank_sentence = re.sub(
                re.escape(word),
                "_____",
                example,
                flags=re.IGNORECASE
            )

        # Nếu vẫn không có chỗ trống
        if blank_sentence == example:

            blank_sentence = (
                f"{example}\n\n"
                f"Điền từ: _____"
            )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word,
            "word": word,
            "example": example,
            "oxford_url": get_oxford_url(word)
        }

    # ========================================================
    # 3. NGHĨA -> GÕ TỪ
    # ========================================================

    elif chosen_q == "SPELLING":

        st.session_state.q_data = {
            "question": meaning,
            "answer": word
        }

    # ========================================================
    # 4. NGỮ CẢNH -> CHỌN NGHĨA
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
            "Sự phát triển",
            "Khả năng thích nghi",
            "Thành tựu",
            "Môi trường",
            "Kinh nghiệm",
            "Sự kiên trì",
            "Cải thiện"
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
            "answer": meaning
        }

    # ========================================================
    # 5. FLASHCARD ĐÚNG / SAI
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
            "answer": answer
        }

    # ========================================================
    # 6. NGHĨA -> CHỌN TỪ
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
            "improve",
            "challenge"
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
            "answer": word
        }


# ============================================================
# 15. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Golden Time: 5 cấp × 4 móc — sai 1 lần rớt 1 móc"
)

now = datetime.now()

due_count = sum(
    1
    for x in st.session_state.deck
    if x["next_review"] <= now
)

tab_options = [
    "⏰ Ôn Tập",
    "🔍 Tra Từ Mới",
    "📋 Sổ Tay"
]

tab_labels = {
    "⏰ Ôn Tập": f"⏰ Ôn Tập ({due_count})",
    "🔍 Tra Từ Mới": "🔍 Tra Từ Mới",
    "📋 Sổ Tay": (
        f"📋 Sổ Tay "
        f"({len(st.session_state.deck)})"
    )
}

selected_tab = st.radio(
    "Navigation",
    options=tab_options,
    format_func=lambda x: tab_labels[x],
    key="active_tab",
    horizontal=True,
    label_visibility="collapsed"
)

st.markdown("---")


# ============================================================
# 16. TAB ÔN TẬP
# ============================================================

if selected_tab == "⏰ Ôn Tập":

    st.subheader(
        "⏰ Ôn tập đúng Thời Điểm Vàng"
    )

    now = datetime.now()

    due_items = [
        x
        for x in st.session_state.deck
        if x["next_review"] <= now
    ]

    # --------------------------------------------
    # Không có từ
    # --------------------------------------------

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang **🔍 Tra Từ Mới** để thêm từ."
        )

    # --------------------------------------------
    # Có từ nhưng chưa đến giờ
    # --------------------------------------------

    elif not due_items:

        st.session_state.review_started = False
        st.session_state.review_item = None
        st.session_state.q_type = None
        st.session_state.q_data = {}

        next_item = min(
            st.session_state.deck,
            key=lambda x: x["next_review"]
        )

        remaining = (
            next_item["next_review"]
            - datetime.now()
        ).total_seconds()

        st.success(
            "🎉 Hiện tại không có từ nào "
            "đến Thời Điểm Vàng."
        )

        col1, col2, col3 = st.columns(3)

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

        with col3:

            hook_display = (
                int(next_item.get("hook", 0))
                + 1
            )

            st.metric(
                "Móc",
                f"{hook_display}/4"
            )

        st.info(
            f"⏰ Còn khoảng "
            f"**{format_remaining(remaining)}**"
        )

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

            <div id="countdown" style="
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

            var now = new Date().getTime();

            var diff = targetTime - now;

            var element =
                document.getElementById("countdown");

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

    # --------------------------------------------
    # Có từ cần ôn
    # --------------------------------------------

    else:

        if not st.session_state.review_started:

            st.success(
                f"🔥 Có **{len(due_items)} từ** "
                f"đang đến Thời Điểm Vàng."
            )

            st.markdown("---")

            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                Mỗi câu trả lời đúng sẽ tiến **1 móc**.

                Sai 1 lần sẽ **rớt 1 móc** và từ đó
                được tạo **một câu hỏi mới ngay**.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review"
            ):

                # Ưu tiên cấp thấp trước
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

            # ----------------------------------------
            # Sau khi sai:
            # tạo câu hỏi mới cho chính từ đó.
            # ----------------------------------------

            if current_item is None:

                due_items = [
                    x
                    for x in st.session_state.deck
                    if x["next_review"]
                    <= datetime.now()
                ]

                if due_items:

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

            if item is None:
                st.rerun()

            # ----------------------------------------
            # STOP
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
            # LEVEL
            # ----------------------------------------

            level = int(
                item.get("level", 0)
            )

            hook = int(
                item.get("hook", 0)
            )

            st.progress(
                get_progress_value(item)
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(level)
                )

            with col2:

                st.caption(
                    f"🎯 Móc {hook + 1}/4"
                )

            current_interval = (
                get_current_interval_minutes(
                    item
                )
            )

            st.caption(
                f"📐 Mốc hiện tại: "
                f"**{format_interval(current_interval)}**"
            )

            # Hiển thị chuỗi 4 móc của cấp
            if level < 5:

                schedule_text = " → ".join(
                    f"{h}h"
                    for h in GOLDEN_SCHEDULE[level]
                )

                st.caption(
                    f"🧠 Cấp {level}: "
                    f"{schedule_text}"
                )

            st.markdown("---")

            # ====================================================
            # DẠNG 1: CHOICE_MEANING
            # ====================================================

            if q_type == "CHOICE_MEANING":

                st.markdown(
                    "### 🎲 TRẮC NGHIỆM CHỌN NGHĨA"
                )

                st.info(
                    f"Từ: **{item['word'].upper()}** "
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
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # ====================================================
            # DẠNG 2: FILL BLANK
            # ====================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                st.info(
                    f"**Câu ví dụ:**\n\n"
                    f"{q_data.get('sentence')}"
                )

                # --------------------------------------------
                # Link Oxford
                # --------------------------------------------

                st.markdown(
                    f"[📖 Xem từ **{item['word']}** "
                    f"trên Oxford Learner's Dictionaries]"
                    f"({q_data.get('oxford_url')})"
                )

                user_ans = st.text_input(
                    "Từ còn thiếu:",
                    key=f"fill_{item['id']}"
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=f"fill_submit_{item['id']}"
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].lower(),
                        item["word"].upper()
                    )

            # ====================================================
            # DẠNG 3: SPELLING
            # ====================================================

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
                    key=f"spell_{item['id']}"
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=f"spell_submit_{item['id']}"
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].lower(),
                        item["word"].upper()
                    )

            # ====================================================
            # DẠNG 4: CONTEXT MATCH
            # ====================================================

            elif q_type == "CONTEXT_MATCH":

                st.markdown(
                    "### 🧠 NGHĨA THEO NGỮ CẢNH"
                )

                st.info(
                    f'"{q_data.get("context")}"'
                )

                st.write(
                    f'Từ **{item["word"].upper()}** '
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
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # ====================================================
            # DẠNG 5: TRUE / FALSE
            # ====================================================

            elif q_type == "FLASHCARD_TRUE_FALSE":

                st.markdown(
                    "### ⚡ FLASHCARD PHẢN XẠ"
                )

                st.info(
                    f"Từ: **{item['word'].upper()}**\n\n"
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
                        key=f"true_{item['id']}"
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
                        key=f"false_{item['id']}"
                    ):

                        process_answer(
                            not q_data["is_true"],
                            "SAI"
                            if not q_data["is_true"]
                            else "ĐÚNG"
                        )

            # ====================================================
            # DẠNG 6: MEANING CHOICE
            # ====================================================

            elif q_type == "MEANING_CHOICE":

                st.markdown(
                    "### 🔤 NGHĨA → CHỌN TỪ TIẾNG ANH"
                )

                st.info(
                    f"Nghĩa: "
                    f"**{q_data.get('question', '').upper()}**"
                )

                st.write(
                    "Chọn từ tiếng Anh "
                    "có nghĩa tương ứng:"
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
                            f"mchoice_opt_"
                            f"{item['id']}_"
                            f"{index}"
                        )
                    ):

                        process_answer(
                            option.lower()
                            == item["word"].lower(),
                            item["word"].upper()
                        )


# ============================================================
# 17. TAB TRA TỪ MỚI
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
        type="primary"
    ):

        if word_input:

            with st.spinner(
                "Đang tra từ..."
            ):

                data = (
                    fetch_word_full_data_FAST(
                        word_input
                    )
                )

            if not data.get(
                "success",
                False
            ):

                if data.get(
                    "translation_error"
                ):

                    st.error(
                        "❌ Đã tìm thấy từ nhưng "
                        "không lấy được nghĩa tiếng Việt. "
                        "Vui lòng thử lại."
                    )

                else:

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
                    "example": example
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

        # --------------------------------------------
        # NGHĨA VIỆT
        # --------------------------------------------

        st.write(
            f"👉 **Nghĩa tiếng Việt:** "
            f"{data['meaning']}"
        )

        st.caption(
            f"💡 Ví dụ: {data['example']}"
        )

        st.markdown(
            f"[📖 Xem **{data['word']}** trên "
            f"Oxford Learner's Dictionaries]"
            f"({get_oxford_url(data['word'])})"
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
                    x["word"].lower()
                    == data["word"].lower()
                    for x in st.session_state.deck
                )

                if exists:

                    st.warning(
                        "Từ này đã có."
                    )

                else:

                    new_item = {

                        "id": get_next_id(),

                        "word": data["word"],

                        "phonetic": data["phonetic"],

                        "meaning": data["meaning"],

                        "example": data["example"],

                        # --------------------------
                        # GOLDEN TIME
                        # --------------------------

                        "level": 0,

                        "hook": 0,

                        "interval": 60,

                        "review_count": 0,

                        "correct_count": 0,

                        "wrong_count": 0,

                        "last_response_time": None,

                        "last_result": None,

                        # Ôn lần đầu ngay lập tức
                        "next_review": datetime.now()
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
                        "⏰ Từ mới bắt đầu ở "
                        "**Cấp 0 — Móc 1/4 — 1 giờ**."
                    )

                    time.sleep(1)

                    st.rerun()


# ============================================================
# 18. TAB SỔ TAY
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
            if x["next_review"]
            <= datetime.now()
        )

        mastered = sum(
            1
            for x in st.session_state.deck
            if x["level"] == 5
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
                "Cấp 5",
                mastered
            )

        st.markdown("---")

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
                    f"⏳ "
                    f"{format_remaining(remaining)}"
                )

            accuracy_total = (
                item.get(
                    "correct_count",
                    0
                )
                +
                item.get(
                    "wrong_count",
                    0
                )
            )

            if accuracy_total > 0:

                accuracy_text = (
                    f"{item.get('correct_count', 0) / accuracy_total * 100:.0f}%"
                )

            else:

                accuracy_text = "—"

            level = int(
                item.get("level", 0)
            )

            hook = int(
                item.get("hook", 0)
            )

            if level >= 5:

                hook_text = "🏆 Mastered"

            else:

                hook_text = (
                    f"Móc {hook + 1}/4"
                )

            table_data.append({

                "Từ":
                    item["word"].upper(),

                "Nghĩa":
                    item["meaning"],

                "Cấp":
                    level,

                "Móc":
                    hook_text,

                "Trạng thái":
                    get_level_name(level),

                "Mốc hiện tại":
                    format_interval(
                        get_current_interval_minutes(
                            item
                        )
                    ),

                "Độ chính xác":
                    accuracy_text,

                "Số lần ôn":
                    item.get(
                        "review_count",
                        0
                    ),

                "Tiếp theo":
                    status
            })

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        # --------------------------------------------
        # Hiển thị bảng Golden Time
        # --------------------------------------------

        st.markdown(
            "### 🧠 Bảng Golden Time"
        )

        golden_table = []

        for level, schedule in GOLDEN_SCHEDULE.items():

            golden_table.append({

                "Cấp":
                    f"Cấp {level}",

                "Móc 1":
                    f"{schedule[0]}h",

                "Móc 2":
                    f"{schedule[1]}h",

                "Móc 3":
                    f"{schedule[2]}h",

                "Móc 4":
                    f"{schedule[3]}h",

            })

        golden_table.append({

            "Cấp":
                "Cấp 5",

            "Móc 1":
                "🏆",

            "Móc 2":
                "🏆",

            "Móc 3":
                "🏆",

            "Móc 4":
                "🏆",
        })

        st.dataframe(
            golden_table,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        # --------------------------------------------
        # XÓA TOÀN BỘ
        # --------------------------------------------

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

            time.sleep(0.5)

            st.rerun()

    else:

        st.info(
            "📚 Sổ tay đang trống."
        )


# ============================================================
# 19. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • "
    "Golden Time 5 cấp × 4 móc"
)
