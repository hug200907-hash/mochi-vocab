import json
import random
import time
import urllib.parse
import urllib.request
import requests
import re
import html

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
# 2. GOLDEN TIME
# ============================================================
#
# Mỗi cấp có 4 MỐC.
#
# Cấp 0:
#   Mốc 1 = 1h
#   Mốc 2 = 4h
#   Mốc 3 = 12h
#   Mốc 4 = 24h
#
# Cấp 1:
#   25h → 28h → 36h → 48h
#
# Cấp 2:
#   49h → 52h → 60h → 72h
#
# Cấp 3:
#   73h → 76h → 84h → 96h
#
# Cấp 4:
#   97h → 100h → 108h → 120h
#
# Sau 4 mốc của Cấp 4 => Cấp 5.
# Cấp 5 giữ ở 120h.
#
# ============================================================

GOLDEN_TIMES = {
    0: [60, 240, 720, 1440],          # 1h, 4h, 12h, 24h
    1: [1500, 1680, 2160, 2880],      # 25h, 28h, 36h, 48h
    2: [2940, 3120, 3600, 4320],      # 49h, 52h, 60h, 72h
    3: [4380, 4560, 5040, 5760],      # 73h, 76h, 84h, 96h
    4: [5820, 6000, 6480, 7200],      # 97h, 100h, 108h, 120h
    5: [7200, 7200, 7200, 7200]       # Cấp 5: giữ 120h
}

MAX_LEVEL = 5
MAX_MILESTONE = 3


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

def get_current_interval(level, milestone):
    level = max(0, min(int(level), MAX_LEVEL))
    milestone = max(0, min(int(milestone), MAX_MILESTONE))

    return GOLDEN_TIMES[level][milestone]


def get_level_name(level):
    names = {
        0: "🆕 Cấp 0 — Mới học",
        1: "🥉 Cấp 1 — Đang hình thành",
        2: "🥈 Cấp 2 — Đã nhớ",
        3: "🥇 Cấp 3 — Nhớ khá tốt",
        4: "💎 Cấp 4 — Nhớ lâu",
        5: "🏆 Cấp 5 — Ghi nhớ rất tốt"
    }

    return names.get(level, "🆕 Cấp 0 — Mới học")


def get_milestone_name(milestone):
    return f"Mốc {milestone + 1}/4"


def get_progress_text(item):
    level = int(item.get("level", 0))
    milestone = int(item.get("milestone", 0))

    if level >= 5:
        return "🏆 Đã đạt Cấp 5"

    return f"{get_level_name(level)} • {get_milestone_name(milestone)}"


def normalize_item_progress(item):
    """
    Chuẩn hóa dữ liệu cũ.

    Nếu dữ liệu cũ chưa có milestone:
    - level 0 => mốc 0
    - level 1 => mốc 0
    ...
    """

    item["level"] = max(
        0,
        min(int(item.get("level", 0)), MAX_LEVEL)
    )

    item["milestone"] = max(
        0,
        min(int(item.get("milestone", 0)), MAX_MILESTONE)
    )

    if item["level"] >= 5:
        item["level"] = 5
        item["milestone"] = 3

    item["interval"] = get_current_interval(
        item["level"],
        item["milestone"]
    )

    return item


def advance_progress(item):
    """
    Trả lời đúng:

    Mốc 1 -> Mốc 2
    Mốc 2 -> Mốc 3
    Mốc 3 -> Mốc 4
    Mốc 4 -> lên cấp mới + Mốc 1

    Cấp 5 giữ nguyên.
    """

    level = int(item.get("level", 0))
    milestone = int(item.get("milestone", 0))

    if level >= MAX_LEVEL:
        item["level"] = MAX_LEVEL
        item["milestone"] = MAX_MILESTONE
        item["interval"] = GOLDEN_TIMES[MAX_LEVEL][MAX_MILESTONE]
        return

    if milestone < MAX_MILESTONE:
        milestone += 1

    else:
        level += 1
        milestone = 0

    item["level"] = level
    item["milestone"] = milestone
    item["interval"] = get_current_interval(level, milestone)


def regress_progress(item):
    """
    Trả lời sai:

    - Tụt đúng 1 mốc.
    - Nếu đang ở Mốc 1 của cấp hiện tại:
        tụt về Mốc 4 của cấp trước.
    - Nếu đang Cấp 0 Mốc 1:
        vẫn ở Cấp 0 Mốc 1.

    Ví dụ:

    Cấp 2 Mốc 3
    sai
    -> Cấp 2 Mốc 2

    Cấp 2 Mốc 1
    sai
    -> Cấp 1 Mốc 4

    Cấp 0 Mốc 1
    sai
    -> Cấp 0 Mốc 1
    """

    level = int(item.get("level", 0))
    milestone = int(item.get("milestone", 0))

    if level == 0 and milestone == 0:
        item["level"] = 0
        item["milestone"] = 0

    elif milestone > 0:
        item["milestone"] = milestone - 1

    else:
        item["level"] = max(0, level - 1)
        item["milestone"] = MAX_MILESTONE

    item["interval"] = get_current_interval(
        item["level"],
        item["milestone"]
    )


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

                # ------------------------------------------------
                # NEXT REVIEW
                # ------------------------------------------------

                if "next_review" not in item:
                    item["next_review"] = datetime.now()

                if isinstance(item["next_review"], str):
                    try:
                        item["next_review"] = datetime.fromisoformat(
                            item["next_review"]
                        )
                    except Exception:
                        item["next_review"] = datetime.now()

                # ------------------------------------------------
                # COUNTERS
                # ------------------------------------------------

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

                # ------------------------------------------------
                # PROGRESS
                # ------------------------------------------------

                if "milestone" not in item:
                    item["milestone"] = 0

                normalize_item_progress(item)

                cleaned_items.append(item)

            st.session_state.deck = cleaned_items

        except Exception:
            st.session_state.deck = []

    st.session_state.data_loaded = True


# ============================================================
# 7. SAVE LOCAL STORAGE
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
# 8. PHÁT ÂM
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
# 9. KIỂM TRA NGHĨA TIẾNG VIỆT
# ============================================================

def looks_like_english_translation(original, translated):

    if not translated:
        return True

    original_clean = re.sub(
        r"[^a-zA-Z]",
        "",
        original.lower()
    )

    translated_clean = re.sub(
        r"[^a-zA-Z]",
        "",
        translated.lower()
    )

    if not translated_clean:
        return True

    # Nếu kết quả dịch gần như chính từ tiếng Anh
    if translated_clean == original_clean:
        return True

    # Nếu chuỗi dịch chỉ toàn ASCII tiếng Anh
    # và không có dấu tiếng Việt
    vietnamese_chars = (
        "ăâđêôơư"
        "áàảãạ"
        "ắằẳẵặ"
        "ấầẩẫậ"
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

    lower_text = translated.lower()

    has_vietnamese_char = any(
        c in lower_text
        for c in vietnamese_chars
    )

    # Một số từ tiếng Việt không có dấu:
    common_vietnamese = [
        "khả năng",
        "phát triển",
        "kinh nghiệm",
        "môi trường",
        "thành tựu",
        "thích nghi",
        "đổi mới",
        "sáng tạo",
        "cải thiện",
        "quan trọng",
        "hiệu quả",
        "giải pháp",
        "vấn đề",
        "sự nghiệp",
        "cơ hội",
        "thành công",
        "thất bại",
        "giảm",
        "tăng",
        "hỗ trợ",
        "giúp đỡ",
        "hành động",
        "học tập",
        "kiến thức",
        "kỹ năng"
    ]

    if has_vietnamese_char:
        return False

    for phrase in common_vietnamese:
        if phrase in lower_text:
            return False

    # Nếu chỉ có từ Latin tiếng Anh thì nghi ngờ
    english_words = translated.split()

    if len(english_words) <= 4:
        return True

    return False


# ============================================================
# 10. DỊCH ANH -> VIỆT
# ============================================================

def translate_single_text(text):

    if not text or not text.strip():
        return ""

    text = text.strip()

    # --------------------------------------------------------
    # CÁCH 1: Google Translate
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

            if translated and not looks_like_english_translation(
                text,
                translated
            ):
                return translated

    except Exception:
        pass

    # --------------------------------------------------------
    # CÁCH 2: MyMemory
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
                data.get("responseData", {})
                .get("translatedText", "")
                .strip()
            )

            if translated and not looks_like_english_translation(
                text,
                translated
            ):
                return translated

    except Exception:
        pass

    return ""


# ============================================================
# 11. TRA DỮ LIỆU TỪ DICTIONARY API
# ============================================================

def fetch_dictionary_data(word):

    url = (
        "https://api.dictionaryapi.dev/"
        "api/v2/entries/en/"
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
                            definition.get(
                                "definition"
                            )
                        )

                        if definition_text:
                            meanings_raw.append({
                                "type": pos,
                                "en": definition_text
                            })

                        example_text = (
                            definition.get(
                                "example"
                            )
                        )

                        if example_text:
                            examples.append(
                                example_text
                            )

                        if len(meanings_raw) >= 5:
                            break

                    if len(meanings_raw) >= 5:
                        break

    except Exception:
        pass

    return {
        "phonetic": phonetic,
        "meanings_raw": meanings_raw,
        "examples": examples
    }


# ============================================================
# 12. LẤY EXAMPLE TỪ OXFORD LEARNER'S DICTIONARIES
# ============================================================
#
# Oxford có example sentences trong các trang entry.
#
# Ví dụ:
# https://www.oxfordlearnersdictionaries.com/
# definition/english/example
#
# Hàm này cố lấy câu ví dụ từ HTML.
#
# Nếu Oxford không trả dữ liệu / chặn request,
# app sẽ fallback về Dictionary API.
#
# ============================================================

def fetch_oxford_example(word):

    word = word.strip().lower()

    if not word:
        return None

    url = (
        "https://www.oxfordlearnersdictionaries.com/"
        "definition/english/"
        f"{urllib.parse.quote(word)}"
    )

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=7
        )

        if response.status_code != 200:
            return None

        page = response.text

        # ----------------------------------------------------
        # Loại script/style
        # ----------------------------------------------------

        page = re.sub(
            r"<script.*?</script>",
            " ",
            page,
            flags=re.DOTALL | re.IGNORECASE
        )

        page = re.sub(
            r"<style.*?</style>",
            " ",
            page,
            flags=re.DOTALL | re.IGNORECASE
        )

        # ----------------------------------------------------
        # Tìm các block example
        # ----------------------------------------------------

        patterns = [

            # <span class="x">example sentence</span>
            r'class=["\'][^"\']*\b(x|example|ex)\b[^"\']*["\'][^>]*>'
            r"(.*?)"
            r"</(?:span|div|p)>",

            # example-item
            r'class=["\'][^"\']*example[^"\']*["\'][^>]*>'
            r"(.*?)"
            r"</(?:span|div|p)>",

            # x/hyperlink style blocks
            r'class=["\'][^"\']*\bx\b[^"\']*["\'][^>]*>'
            r"(.*?)"
            r"</span>"
        ]

        candidates = []

        for pattern in patterns:

            matches = re.findall(
                pattern,
                page,
                flags=re.DOTALL | re.IGNORECASE
            )

            for match in matches:

                if isinstance(match, tuple):
                    text = match[-1]
                else:
                    text = match

                text = re.sub(
                    r"<[^>]+>",
                    " ",
                    text
                )

                text = html.unescape(text)

                text = re.sub(
                    r"\s+",
                    " ",
                    text
                ).strip()

                if not text:
                    continue

                # Bỏ câu quá ngắn
                if len(text.split()) < 4:
                    continue

                # Không lấy text menu / UI
                bad_words = [
                    "Oxford Learner",
                    "See full entry",
                    "Questions about grammar",
                    "Definitions on the go",
                    "Join our community",
                    "Want to learn more"
                ]

                if any(
                    bad.lower() in text.lower()
                    for bad in bad_words
                ):
                    continue

                candidates.append(text)

        # ----------------------------------------------------
        # Lọc trùng
        # ----------------------------------------------------

        unique_candidates = []

        for candidate in candidates:

            if candidate not in unique_candidates:
                unique_candidates.append(candidate)

        # ----------------------------------------------------
        # Ưu tiên câu có chứa từ đang tra
        # ----------------------------------------------------

        for candidate in unique_candidates:

            if re.search(
                r"\b"
                + re.escape(word)
                + r"\b",
                candidate,
                flags=re.IGNORECASE
            ):
                return candidate

        if unique_candidates:
            return unique_candidates[0]

    except Exception:
        pass

    return None


# ============================================================
# 13. TẠO NGHĨA TIẾNG VIỆT
# ============================================================

def get_vietnamese_meaning(word, dictionary_data):

    # Dịch chính từ tiếng Anh sang tiếng Việt
    translated = translate_single_text(word)

    if translated:
        return translated

    # Nếu không dịch được thì thử dịch definition tiếng Anh
    definitions = dictionary_data.get(
        "meanings_raw",
        []
    )

    if definitions:

        first_definition = definitions[0].get(
            "en",
            ""
        )

        if first_definition:

            translated_definition = translate_single_text(
                first_definition
            )

            if translated_definition:
                return translated_definition

    # Không trả lại chính từ tiếng Anh.
    return "Chưa lấy được nghĩa tiếng Việt"


# ============================================================
# 14. TRA FULL DATA
# ============================================================

def fetch_word_full_data_FAST(word):

    dictionary_data = fetch_dictionary_data(
        word
    )

    meanings_raw = dictionary_data.get(
        "meanings_raw",
        []
    )

    if not meanings_raw:
        return {
            "success": False
        }

    phonetic = dictionary_data.get(
        "phonetic",
        f"/{word}/"
    )

    # --------------------------------------------------------
    # Nghĩa tiếng Việt
    # --------------------------------------------------------

    short_vn = get_vietnamese_meaning(
        word,
        dictionary_data
    )

    # --------------------------------------------------------
    # Oxford example
    # --------------------------------------------------------

    oxford_example = fetch_oxford_example(
        word
    )

    # --------------------------------------------------------
    # Fallback Dictionary API example
    # --------------------------------------------------------

    examples = dictionary_data.get(
        "examples",
        []
    )

    if oxford_example:
        example = oxford_example

    elif examples:
        example = examples[0]

    else:
        example = (
            f"It is important to understand {word}."
        )

    return {
        "success": True,
        "phonetic": phonetic,
        "short_vn": short_vn,
        "examples": [example],
        "source": (
            "Oxford Learner's Dictionaries"
            if oxford_example
            else "Dictionary API"
        )
    }


# ============================================================
# 15. EXAMPLE ONLINE FALLBACK
# ============================================================

def fetch_online_word_data(word):

    # Ưu tiên Oxford
    oxford_example = fetch_oxford_example(
        word
    )

    if oxford_example:
        return oxford_example

    # Fallback Dictionary API
    data = fetch_dictionary_data(
        word
    )

    examples = data.get(
        "examples",
        []
    )

    if examples:
        return examples[0]

    return None


# ============================================================
# 16. ID
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
# 17. TẠO CÂU HỎI
# ============================================================
#
# BỎ:
# - AUDIO_CHOICE
#
# GIỮ:
# 1. CHOICE_MEANING
# 2. FILL_BLANK
# 3. SPELLING
# 4. CONTEXT_MATCH
# 5. FLASHCARD_TRUE_FALSE
# 6. MEANING_CHOICE
#
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

    # Reset question data
    st.session_state.q_data = {}

    # Bắt đầu tính thời gian từ lúc câu hỏi mới xuất hiện
    st.session_state.review_start_time = time.time()

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
    # Nếu chưa có example => lấy Oxford
    # --------------------------------------------------------

    if not example:

        online_example = fetch_online_word_data(
            word
        )

        if online_example:

            example = online_example
            item["example"] = example

        else:

            example = (
                f"The word '{word}' is "
                f"very important."
            )

    # --------------------------------------------------------
    # Các từ khác trong deck
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
            "Sự đổi mới"
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
    # 2. ĐIỀN TỪ VÀO CHỖ TRỐNG
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        # Tạo chỗ trống cho từ trong câu Oxford
        blank_sentence = re.sub(
            r"\b"
            + re.escape(word)
            + r"\b",
            "_____",
            example,
            flags=re.IGNORECASE
        )

        # Nếu Oxford example không chứa đúng word
        if blank_sentence == example:

            # Thử thêm từ vào cuối câu
            blank_sentence = (
                f"{example} (_____)"
            )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word,
            "word": word,
            "source": item.get(
                "example_source",
                "Oxford Learner's Dictionaries"
            )
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
            "Sự kiên trì",
            "Sự đổi mới"
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

        if deck_words:

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
            "achievement"
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
# 18. CHỌN TỪ TIẾP THEO
# ============================================================

def choose_next_due_item():

    now = datetime.now()

    due_items = [
        x
        for x in st.session_state.deck
        if x.get("next_review", now) <= now
    ]

    if not due_items:
        return None

    # Ưu tiên cấp thấp hơn
    min_level = min(
        int(x.get("level", 0))
        for x in due_items
    )

    candidates = [
        x
        for x in due_items
        if int(x.get("level", 0))
        == min_level
    ]

    return random.choice(
        candidates
    )


# ============================================================
# 19. XỬ LÝ ĐÁP ÁN
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

    old_milestone = int(
        item.get("milestone", 0)
    )

    # ========================================================
    # ĐÚNG
    # ========================================================

    if is_correct:

        advance_progress(item)

        item["correct_count"] = int(
            item.get("correct_count", 0)
        ) + 1

        item["last_result"] = "correct"

        st.success(
            "✨ Chính xác!"
        )

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        new_level = int(
            item["level"]
        )

        new_milestone = int(
            item["milestone"]
        )

        # ----------------------------------------------------
        # Lên cấp
        # ----------------------------------------------------

        if new_level > old_level:

            st.success(
                f"📈 LÊN CẤP: "
                f"Cấp {old_level} → "
                f"Cấp {new_level}"
            )

            st.success(
                "🎉 Đã hoàn thành đủ 4 mốc "
                "của cấp trước!"
            )

        else:

            st.info(
                f"📍 Mốc: "
                f"{old_milestone + 1}/4 → "
                f"{new_milestone + 1}/4"
            )

        st.info(
            "🧠 Thời Điểm Vàng tiếp theo: "
            f"**{format_interval(item['interval'])}**"
        )

        if new_level == 5:

            st.balloons()

            st.success(
                "🏆 Từ này đã đạt Cấp 5!"
            )

    # ========================================================
    # SAI
    # ========================================================

    else:

        regress_progress(item)

        item["wrong_count"] = int(
            item.get("wrong_count", 0)
        ) + 1

        item["last_result"] = "wrong"

        st.error(
            "❌ Chưa chính xác."
        )

        st.warning(
            f"Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        new_level = int(
            item["level"]
        )

        new_milestone = int(
            item["milestone"]
        )

        st.warning(
            f"📉 Tụt 1 mốc: "
            f"Cấp {old_level} Mốc {old_milestone + 1}"
            f" → "
            f"Cấp {new_level} Mốc {new_milestone + 1}"
        )

        # ----------------------------------------------------
        # QUAN TRỌNG:
        # Sai => ôn lại ngay
        # và lần tới tạo câu hỏi mới
        # ----------------------------------------------------

        item["next_review"] = datetime.now()

        st.info(
            "🔄 Từ này sẽ được hỏi lại ngay "
            "với **một câu hỏi mới**."
        )

    # ========================================================
    # CHUNG
    # ========================================================

    item["review_count"] = int(
        item.get("review_count", 0)
    ) + 1

    item["last_response_time"] = round(
        response_time,
        2
    )

    # --------------------------------------------------------
    # Nếu đúng => next_review theo Golden Time
    # Nếu sai => next_review = ngay bây giờ
    # --------------------------------------------------------

    if is_correct:

        item["next_review"] = (
            datetime.now()
            + timedelta(
                minutes=int(
                    item["interval"]
                )
            )
        )

    save_deck()

    # --------------------------------------------------------
    # Xóa câu hỏi hiện tại
    # --------------------------------------------------------

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}
    st.session_state.review_start_time = 0

    # Không dừng session ôn.
    # Sai thì câu tiếp theo sẽ được tạo mới ngay.
    st.rerun()


# ============================================================
# 20. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Dynamic Golden Time • "
    "4 mốc mỗi cấp"
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
    "⏰ Ôn Tập": (
        f"⏰ Ôn Tập ({due_count})"
    ),
    "🔍 Tra Từ Mới":
        "🔍 Tra Từ Mới",
    "📋 Sổ Tay": (
        f"📋 Sổ Tay "
        f"({len(st.session_state.deck)})"
    )
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
# 21. TAB ÔN TẬP
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
    # Chưa đến giờ
    # --------------------------------------------------------

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
            f"📍 {get_progress_text(next_item)}"
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

                MochiVocab sẽ chọn từ cần ôn,
                tạo một câu hỏi ngẫu nhiên và
                bắt đầu tính thời gian phản hồi.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review"
            ):

                item = choose_next_due_item()

                if item:

                    st.session_state.review_started = True

                    prepare_review_question(
                        item
                    )

                    st.rerun()

        else:

            # ------------------------------------------------
            # Nếu chưa có câu hỏi
            # ------------------------------------------------

            current_item = (
                st.session_state.review_item
            )

            if current_item is None:

                item = choose_next_due_item()

                if item:

                    prepare_review_question(
                        item
                    )

                    st.rerun()

                else:

                    st.session_state.review_started = False
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
            # PROGRESS
            # ------------------------------------------------

            level = int(
                item["level"]
            )

            milestone = int(
                item.get("milestone", 0)
            )

            if level < 5:

                progress_value = (
                    milestone + 1
                ) / 4

            else:

                progress_value = 1.0

            st.progress(
                progress_value
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(level)
                )

                st.caption(
                    f"📍 Mốc "
                    f"{milestone + 1}/4"
                )

            with col2:

                st.caption(
                    f"Đã ôn: "
                    f"{item.get('review_count', 0)} lần"
                )

            current_interval = (
                item.get(
                    "interval",
                    get_current_interval(
                        level,
                        milestone
                    )
                )
            )

            st.caption(
                "📐 Mốc hiện tại: "
                f"**{format_interval(current_interval)}**"
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
            # DẠNG 2: FILL BLANK
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                source = q_data.get(
                    "source",
                    "Oxford Learner's Dictionaries"
                )

                st.caption(
                    f"📖 Ví dụ từ: {source}"
                )

                st.info(
                    f"**{q_data.get('sentence')}**"
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

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].lower(),
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 3: SPELLING
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

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].lower(),
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 4: CONTEXT MATCH
            # =================================================

            elif q_type == "CONTEXT_MATCH":

                st.markdown(
                    "### 🧠 NGHĨA THEO NGỮ CẢNH"
                )

                st.info(
                    f'"{q_data.get("context")}"'
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
            # DẠNG 5: TRUE / FALSE
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
            # DẠNG 6: MEANING CHOICE
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

                        process_answer(
                            option.lower()
                            == item["word"].lower(),
                            item["word"].upper()
                        )


# ============================================================
# 22. TAB TRA TỪ MỚI
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
                "Đang tra Oxford + dịch tiếng Việt..."
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
                        f"It is important to "
                        f"understand {word_input}."
                    )
                )

                st.session_state.temp_word = {
                    "word": word_input,
                    "phonetic": data["phonetic"],
                    "meaning": data["short_vn"],
                    "example": example,
                    "example_source": data.get(
                        "source",
                        "Dictionary API"
                    )
                }

    data = (
        st.session_state.temp_word
    )

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
            f"💡 Ví dụ: "
            f"{data['example']}"
        )

        st.caption(
            f"📖 Nguồn ví dụ: "
            f"{data.get('example_source', 'Dictionary API')}"
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

                    new_item = {

                        "id":
                            get_next_id(),

                        "word":
                            data["word"],

                        "phonetic":
                            data["phonetic"],

                        "meaning":
                            data["meaning"],

                        "example":
                            data["example"],

                        "example_source":
                            data.get(
                                "example_source",
                                "Dictionary API"
                            ),

                        # ------------------------------------
                        # GOLDEN TIME
                        # ------------------------------------

                        "level":
                            0,

                        "milestone":
                            0,

                        "interval":
                            GOLDEN_TIMES[0][0],

                        # ------------------------------------
                        # STATISTICS
                        # ------------------------------------

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

                        # ------------------------------------
                        # ÔN NGAY
                        # ------------------------------------

                        "next_review":
                            datetime.now()
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
                        "⏰ Mốc đầu tiên: "
                        "**1 giờ**"
                    )

                    time.sleep(0.7)

                    st.rerun()


# ============================================================
# 23. TAB SỔ TAY
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

            normalize_item_progress(
                item
            )

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
                    f"(("
                    item.get(
                        "correct_count",
                        0
                    )
                    / accuracy_total
                    * 100
                    ): .0f}%"
                ).replace(
                    " ",
                    ""
                )

            else:

                accuracy_text = "—"

            table_data.append({

                "Từ":
                    item["word"].upper(),

                "Nghĩa tiếng Việt":
                    item["meaning"],

                "Cấp":
                    item["level"],

                "Mốc":
                    f"{item['milestone'] + 1}/4",

                "Trạng thái":
                    get_level_name(
                        item["level"]
                    ),

                "Golden Time":
                    format_interval(
                        item.get(
                            "interval",
                            60
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

        # ----------------------------------------------------
        # Hiển thị bảng Golden Time
        # ----------------------------------------------------

        st.markdown(
            "### ⏰ Bảng Golden Time"
        )

        golden_table = []

        for level in range(0, 5):

            golden_table.append({

                "Cấp":
                    f"Cấp {level}",

                "Mốc 1":
                    format_interval(
                        GOLDEN_TIMES[level][0]
                    ),

                "Mốc 2":
                    format_interval(
                        GOLDEN_TIMES[level][1]
                    ),

                "Mốc 3":
                    format_interval(
                        GOLDEN_TIMES[level][2]
                    ),

                "Mốc 4":
                    format_interval(
                        GOLDEN_TIMES[level][3]
                    )
            })

        golden_table.append({

            "Cấp":
                "🏆 Cấp 5",

            "Mốc 1":
                "120 giờ",

            "Mốc 2":
                "120 giờ",

            "Mốc 3":
                "120 giờ",

            "Mốc 4":
                "120 giờ"
        })

        st.dataframe(
            golden_table,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        st.warning(
            "⚠️ Xóa toàn bộ sổ tay không thể hoàn tác."
        )

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
# 24. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • "
    "Golden Time 4 Mốc / Cấp"
)
