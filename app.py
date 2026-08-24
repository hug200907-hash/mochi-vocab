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
# 2. CẤU HÌNH OXFORD API
# ============================================================
#
# Oxford Dictionary API có thể trả:
# - Definition
# - Example
# - Pronunciation
# - Part of speech
#
# Nếu chưa có API key:
# để trống 2 biến bên dưới.
#
# App sẽ tự động fallback sang Dictionary API.
#
# Oxford API:
# https://developer.oxforddictionaries.com/
#
# ============================================================

OXFORD_APP_ID = ""
OXFORD_APP_KEY = ""

OXFORD_LANGUAGE = "en-gb"


# ============================================================
# 3. CẤU HÌNH GOLDEN TIME
# ============================================================
#
# Mỗi cấp có 4 MÓC.
#
# Cấp 0:
# Móc 1 = 1h
# Móc 2 = 4h
# Móc 3 = 12h
# Móc 4 = 24h
#
# Đủ 4 móc -> lên Cấp 1
#
# Cấp 1:
# 25h -> 28h -> 36h -> 48h
#
# ...
#
# Cấp 5:
# 97h -> 100h -> 108h -> 120h
#
# Cấp 5 đạt móc 4 thì giữ Cấp 5.
#
# ============================================================

GOLDEN_TIME = {
    0: [60, 240, 720, 1440],
    1: [1500, 1680, 2160, 2880],
    2: [2940, 3120, 3600, 4320],
    3: [4380, 4560, 5040, 5760],
    4: [5820, 6000, 6480, 7200],
    5: [5820, 6000, 6480, 7200],
}

MAX_LEVEL = 5
MAX_HOOK = 4


# ============================================================
# 4. CẤU HÌNH TỐC ĐỘ TRẢ LỜI
# ============================================================
#
# Tốc độ không còn làm thay đổi Golden Time.
#
# Tuy nhiên vẫn lưu response time để:
# - thống kê
# - hiển thị
#
# ============================================================


# ============================================================
# 5. SESSION STATE
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
# 6. FORMAT THỜI GIAN
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
        return (
            f"{days} ngày "
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        )

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# ============================================================
# 7. GOLDEN TIME HELPER
# ============================================================

def get_level_name(level):
    names = {
        0: "🆕 Cấp 0 — Mới học",
        1: "🥉 Cấp 1 — Đang hình thành",
        2: "🥈 Cấp 2 — Đã nhớ",
        3: "🥇 Cấp 3 — Nhớ khá tốt",
        4: "💎 Cấp 4 — Nhớ lâu",
        5: "🏆 Cấp 5 — Ghi nhớ rất tốt"
    }

    return names.get(
        level,
        "🆕 Cấp 0 — Mới học"
    )


def get_hook_name(hook):
    names = {
        0: "Chưa có móc",
        1: "Móc 1/4",
        2: "Móc 2/4",
        3: "Móc 3/4",
        4: "Móc 4/4"
    }

    return names.get(hook, "Móc 0/4")


def get_current_interval(level, hook):
    level = max(
        0,
        min(int(level), MAX_LEVEL)
    )

    hook = max(
        0,
        min(int(hook), MAX_HOOK)
    )

    if hook <= 0:
        return GOLDEN_TIME[level][0]

    return GOLDEN_TIME[level][hook - 1]


def get_next_interval_after_correct(item):
    """
    Khi trả lời đúng:
    - móc tăng 1
    - đủ 4 móc thì level +1
    """

    old_level = int(item.get("level", 0))
    old_hook = int(item.get("hook", 0))

    old_level = max(
        0,
        min(old_level, MAX_LEVEL)
    )

    old_hook = max(
        0,
        min(old_hook, MAX_HOOK)
    )

    new_level = old_level
    new_hook = old_hook + 1

    if new_hook > MAX_HOOK:

        if old_level < MAX_LEVEL:
            new_level = old_level + 1
            new_hook = 0
        else:
            # Cấp 5 không lên nữa.
            # Giữ cấp 5 và giữ móc 4.
            new_level = MAX_LEVEL
            new_hook = MAX_HOOK

    if new_level == MAX_LEVEL:
        if new_hook == 0:
            new_hook = 1

    if new_hook == 0:
        interval = GOLDEN_TIME[new_level][0]
    else:
        interval = GOLDEN_TIME[new_level][new_hook - 1]

    return new_level, new_hook, interval


def get_next_interval_after_wrong(item):
    """
    Sai 1 lần:
    - rớt đúng 1 móc
    - không được rớt quá Cấp 0 / Móc 0
    """

    old_level = int(item.get("level", 0))
    old_hook = int(item.get("hook", 0))

    old_level = max(
        0,
        min(old_level, MAX_LEVEL)
    )

    old_hook = max(
        0,
        min(old_hook, MAX_HOOK)
    )

    # --------------------------------------------------------
    # Trường hợp đang có móc
    # --------------------------------------------------------

    if old_hook > 0:

        new_level = old_level
        new_hook = old_hook - 1

    # --------------------------------------------------------
    # Nếu đang Móc 0:
    # rớt về cấp trước, Móc 4
    #
    # Ví dụ:
    # Cấp 2 Móc 0
    # sai
    # -> Cấp 1 Móc 4
    # --------------------------------------------------------

    else:

        if old_level > 0:
            new_level = old_level - 1
            new_hook = MAX_HOOK
        else:
            new_level = 0
            new_hook = 0

    if new_hook == 0:
        interval = GOLDEN_TIME[new_level][0]
    else:
        interval = GOLDEN_TIME[new_level][new_hook - 1]

    return new_level, new_hook, interval


def calculate_next_after_answer(
    item,
    is_correct
):
    if is_correct:
        return get_next_interval_after_correct(item)

    return get_next_interval_after_wrong(item)


# ============================================================
# 8. LOAD & SAVE LOCAL STORAGE
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

                # ------------------------------------------------
                # MIGRATION DỮ LIỆU CŨ
                # ------------------------------------------------

                if "next_review" not in item:
                    item["next_review"] = datetime.now()

                if isinstance(
                    item["next_review"],
                    str
                ):

                    try:
                        item["next_review"] = (
                            datetime.fromisoformat(
                                item["next_review"]
                            )
                        )
                    except Exception:
                        item["next_review"] = datetime.now()

                # ------------------------------------------------
                # LEVEL
                # ------------------------------------------------

                item["level"] = max(
                    0,
                    min(
                        int(item.get("level", 0)),
                        MAX_LEVEL
                    )
                )

                # ------------------------------------------------
                # HOOK
                #
                # Dữ liệu cũ chưa có hook.
                # Cho về 0 để dùng hệ thống mới.
                # ------------------------------------------------

                item["hook"] = max(
                    0,
                    min(
                        int(item.get("hook", 0)),
                        MAX_HOOK
                    )
                )

                # ------------------------------------------------
                # INTERVAL
                # ------------------------------------------------

                if "interval" not in item:

                    item["interval"] = (
                        GOLDEN_TIME[
                            item["level"]
                        ][0]
                    )

                item["interval"] = max(
                    60,
                    min(
                        int(item["interval"]),
                        60 * 24 * 60
                    )
                )

                # ------------------------------------------------
                # STATISTICS
                # ------------------------------------------------

                item["review_count"] = int(
                    item.get(
                        "review_count",
                        0
                    )
                )

                item["correct_count"] = int(
                    item.get(
                        "correct_count",
                        0
                    )
                )

                item["wrong_count"] = int(
                    item.get(
                        "wrong_count",
                        0
                    )
                )

                item["last_response_time"] = (
                    item.get(
                        "last_response_time",
                        None
                    )
                )

                item["last_result"] = (
                    item.get(
                        "last_result",
                        None
                    )
                )

                item["question_wrong_streak"] = int(
                    item.get(
                        "question_wrong_streak",
                        0
                    )
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

        if isinstance(
            copy_item.get("next_review"),
            datetime
        ):
            copy_item["next_review"] = (
                copy_item["next_review"].isoformat()
            )

        serializable_deck.append(
            copy_item
        )

    local_storage.setItem(
        "mochi_deck_data",
        json.dumps(
            serializable_deck,
            ensure_ascii=False
        )
    )


# ============================================================
# 9. PHÁT ÂM
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
# 10. TRANSLATE
# ============================================================

def translate_single_text(text):

    if not text or not text.strip():
        return text

    try:

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single?"
            "client=gtx&sl=en&tl=vi&dt=t&q="
            f"{urllib.parse.quote(text.strip())}"
        )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=3
        ) as response:

            data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

            return "".join(
                item[0]
                for item in data[0]
                if item[0]
            ).strip()

    except Exception:
        return text


# ============================================================
# 11. OXFORD API
# ============================================================

def fetch_oxford_word_data(word):

    if not OXFORD_APP_ID or not OXFORD_APP_KEY:
        return {
            "success": False,
            "reason": "missing_credentials"
        }

    try:

        encoded_word = urllib.parse.quote(
            word.strip().lower()
        )

        url = (
            "https://od-api.oxforddictionaries.com/"
            f"api/v2/words/{OXFORD_LANGUAGE}"
            f"?q={encoded_word}"
            "&fields=definitions,examples,"
            "pronunciations,lexicalCategories"
        )

        headers = {
            "app_id": OXFORD_APP_ID,
            "app_key": OXFORD_APP_KEY,
            "Accept": "application/json"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=5
        )

        if response.status_code != 200:
            return {
                "success": False,
                "reason": f"http_{response.status_code}"
            }

        data = response.json()

        examples = []
        definitions = []
        phonetic = ""
        part_of_speech = ""

        # ----------------------------------------------------
        # Pronunciation
        # ----------------------------------------------------

        for pronunciation in data.get(
            "results",
            []
        ):

            for lexical_entry in pronunciation.get(
                "lexicalEntries",
                []
            ):

                if not part_of_speech:
                    part_of_speech = (
                        lexical_entry.get(
                            "lexicalCategory",
                            {}
                        ).get(
                            "text",
                            ""
                        )
                    )

                for pron in lexical_entry.get(
                    "pronunciations",
                    []
                ):

                    if pron.get("phoneticSpelling"):
                        phonetic = (
                            pron["phoneticSpelling"]
                        )

                        break

                if phonetic:
                    break

            if phonetic:
                break

        # ----------------------------------------------------
        # Definitions + Examples
        # ----------------------------------------------------

        for result in data.get(
            "results",
            []
        ):

            for lexical_entry in result.get(
                "lexicalEntries",
                []
            ):

                if not part_of_speech:
                    part_of_speech = (
                        lexical_entry.get(
                            "lexicalCategory",
                            {}
                        ).get(
                            "text",
                            ""
                        )
                    )

                for entry in lexical_entry.get(
                    "entries",
                    []
                ):

                    for sense in entry.get(
                        "senses",
                        []
                    ):

                        for definition in sense.get(
                            "definitions",
                            []
                        ):

                            if definition:
                                definitions.append(
                                    definition
                                )

                        for example_obj in sense.get(
                            "examples",
                            []
                        ):

                            example_text = (
                                example_obj.get(
                                    "text",
                                    ""
                                )
                            )

                            if example_text:
                                examples.append(
                                    example_text
                                )

                        # Một vài response có examples
                        # nằm trong subsenses.
                        for subsense in sense.get(
                            "subsenses",
                            []
                        ):

                            for definition in subsense.get(
                                "definitions",
                                []
                            ):

                                if definition:
                                    definitions.append(
                                        definition
                                    )

                            for example_obj in subsense.get(
                                "examples",
                                []
                            ):

                                example_text = (
                                    example_obj.get(
                                        "text",
                                        ""
                                    )
                                )

                                if example_text:
                                    examples.append(
                                        example_text
                                    )

        # ----------------------------------------------------
        # Làm sạch
        # ----------------------------------------------------

        definitions = list(
            dict.fromkeys(
                x.strip()
                for x in definitions
                if x and x.strip()
            )
        )

        examples = list(
            dict.fromkeys(
                x.strip()
                for x in examples
                if x and x.strip()
            )
        )

        if not definitions and not examples:
            return {
                "success": False,
                "reason": "empty_result"
            }

        # ----------------------------------------------------
        # Translate definition đầu tiên sang tiếng Việt
        # ----------------------------------------------------

        if definitions:

            vn_meaning = translate_single_text(
                definitions[0]
            )

        else:

            vn_meaning = translate_single_text(
                word
            )

        return {
            "success": True,
            "source": "Oxford",
            "phonetic": phonetic or f"/{word}/",
            "meaning": vn_meaning,
            "definition_en": (
                definitions[0]
                if definitions
                else ""
            ),
            "definitions": definitions[:3],
            "examples": examples[:5],
            "example": (
                examples[0]
                if examples
                else ""
            ),
            "part_of_speech": part_of_speech
        }

    except Exception as e:

        return {
            "success": False,
            "reason": str(e)
        }


# ============================================================
# 12. DICTIONARY API FALLBACK
# ============================================================

def fetch_dictionary_word_data(word):

    url = (
        "https://api.dictionaryapi.dev/"
        "api/v2/entries/en/"
        f"{urllib.parse.quote(word)}"
    )

    meanings_raw = []
    examples = []
    phonetic = f"/{word}/"
    part_of_speech = ""

    try:

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            req,
            timeout=4
        ) as response:

            data = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        if isinstance(data, list) and data:

            first = data[0]

            phonetic = (
                first.get(
                    "phonetic"
                )
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

                if not part_of_speech:
                    part_of_speech = pos

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

                        meanings_raw.append(
                            {
                                "type": pos,
                                "en": definition_text
                            }
                        )

                    example = definition.get(
                        "example"
                    )

                    if example:
                        examples.append(
                            example
                        )

                    if len(meanings_raw) >= 3:
                        break

                if len(meanings_raw) >= 3:
                    break

    except Exception:
        return {
            "success": False
        }

    if not meanings_raw:
        return {
            "success": False
        }

    short_vn = translate_single_text(
        word
    )

    return {
        "success": True,
        "source": "Dictionary API",
        "phonetic": phonetic,
        "meaning": short_vn,
        "definition_en": meanings_raw[0]["en"],
        "definitions": [
            x["en"]
            for x in meanings_raw
        ],
        "examples": examples[:5],
        "example": (
            examples[0]
            if examples
            else ""
        ),
        "part_of_speech": part_of_speech
    }


# ============================================================
# 13. TRA TỪ TỔNG HỢP
# ============================================================

def fetch_word_full_data_FAST(word):

    # --------------------------------------------------------
    # 1. Oxford
    # --------------------------------------------------------

    oxford = fetch_oxford_word_data(
        word
    )

    if oxford.get("success"):
        return oxford

    # --------------------------------------------------------
    # 2. Dictionary API
    # --------------------------------------------------------

    dictionary_data = (
        fetch_dictionary_word_data(
            word
        )
    )

    return dictionary_data


# ============================================================
# 14. LẤY EXAMPLE CHO CÂU ĐIỀN TỪ
# ============================================================

def fetch_online_word_data(word):

    # --------------------------------------------------------
    # Ưu tiên Oxford
    # --------------------------------------------------------

    oxford = fetch_oxford_word_data(
        word
    )

    if oxford.get("success"):

        example = oxford.get(
            "example",
            ""
        )

        if example:
            return example

    # --------------------------------------------------------
    # Fallback Dictionary API
    # --------------------------------------------------------

    dictionary_data = (
        fetch_dictionary_word_data(
            word
        )
    )

    if dictionary_data.get("success"):

        example = dictionary_data.get(
            "example",
            ""
        )

        if example:
            return example

    return None


# ============================================================
# 15. GET ID
# ============================================================

def get_next_id():

    if not st.session_state.deck:
        return 1

    return (
        max(
            int(
                x.get(
                    "id",
                    0
                )
            )
            for x in st.session_state.deck
        )
        + 1
    )


# ============================================================
# 16. XỬ LÝ CÂU TRẢ LỜI
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

    # --------------------------------------------------------
    # TÍNH CẤP + MÓC MỚI
    # --------------------------------------------------------

    (
        new_level,
        new_hook,
        new_interval
    ) = calculate_next_after_answer(
        item,
        is_correct
    )

    # --------------------------------------------------------
    # UPDATE ITEM
    # --------------------------------------------------------

    item["level"] = new_level
    item["hook"] = new_hook
    item["interval"] = new_interval

    item["review_count"] = (
        int(
            item.get(
                "review_count",
                0
            )
        )
        + 1
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

        item["question_wrong_streak"] = 0
        item["last_result"] = "correct"

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

        item["question_wrong_streak"] = (
            int(
                item.get(
                    "question_wrong_streak",
                    0
                )
            )
            + 1
        )

        item["last_result"] = "wrong"

    item["last_response_time"] = round(
        response_time,
        2
    )

    item["next_review"] = (
        datetime.now()
        + timedelta(
            minutes=new_interval
        )
    )

    # --------------------------------------------------------
    # HIỂN THỊ KẾT QUẢ
    # --------------------------------------------------------

    if is_correct:

        st.success(
            "✨ Chính xác!"
        )

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        if new_level > old_level:

            st.success(
                f"📈 Đã đủ 4 móc! "
                f"Cấp độ: "
                f"**{old_level} → {new_level}**"
            )

        else:

            st.info(
                f"📌 Móc: "
                f"**{old_hook}/4 → {new_hook}/4**"
            )

        st.info(
            f"⏰ Thời Điểm Vàng tiếp theo: "
            f"**{format_interval(new_interval)}**"
        )

        if new_level == 5:

            st.balloons()

            st.success(
                "🏆 Từ này đã đạt Cấp 5!"
            )

    else:

        st.error(
            "❌ Chưa chính xác."
        )

        st.warning(
            f"Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        # ----------------------------------------------------
        # Hiển thị tụt móc
        # ----------------------------------------------------

        if new_level < old_level:

            st.warning(
                f"📉 Rớt cấp: "
                f"**Cấp {old_level} → "
                f"Cấp {new_level}**"
            )

        else:

            st.warning(
                f"📉 Rớt móc: "
                f"**{old_hook}/4 → "
                f"{new_hook}/4**"
            )

        st.info(
            f"🔄 Thời Điểm Vàng mới: "
            f"**{format_interval(new_interval)}**"
        )

        st.info(
            "🔁 Từ này sẽ được tạo câu hỏi mới "
            "ở lần ôn tiếp theo."
        )

    save_deck()

    # --------------------------------------------------------
    # RESET QUESTION
    # --------------------------------------------------------

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    time.sleep(1.2)

    st.rerun()


# ============================================================
# 17. TẠO CÂU HỎI
# ============================================================

def prepare_review_question(item):

    # ========================================================
    # 6 DẠNG CÂU HỎI
    #
    # ĐÃ BỎ:
    # AUDIO_CHOICE
    #
    # ========================================================

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

    # ========================================================
    # LẤY EXAMPLE
    # ========================================================

    if not example:

        online_example = (
            fetch_online_word_data(
                word
            )
        )

        if online_example:

            example = online_example

            # Lưu luôn vào item để những lần sau
            # không cần request API nữa.

            item["example"] = example

            save_deck()

    if not example:

        example = (
            f"The word '{word}' "
            f"is used in this sentence."
        )

    # ========================================================
    # DISTRACTORS
    # ========================================================

    deck_words = [
        x.get(
            "word",
            ""
        ).strip()

        for x in st.session_state.get(
            "deck",
            []
        )

        if (
            x.get(
                "word",
                ""
            ).strip().lower()
            != word.lower()
            and
            x.get(
                "word",
                ""
            ).strip()
        )
    ]

    deck_meanings = [
        x.get(
            "meaning",
            ""
        ).strip()

        for x in st.session_state.get(
            "deck",
            []
        )

        if (
            x.get(
                "meaning",
                ""
            ).strip()
            != meaning
            and
            x.get(
                "meaning",
                ""
            ).strip()
        )
    ]

    # ========================================================
    # FALLBACK MEANINGS
    # ========================================================

    fallback_meanings = [
        "Sự phát triển",
        "Khả năng thích nghi",
        "Thành tựu",
        "Môi trường",
        "Kinh nghiệm",
        "Sự kiên cường",
        "Cơ hội",
        "Thách thức"
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
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        # ----------------------------------------------------
        # Tìm chính xác từ cần học trong câu.
        #
        # Ví dụ:
        #
        # Oxford:
        # "The company showed great resilience."
        #
        # Thành:
        # "The company showed great _____."
        # ----------------------------------------------------

        blank_sentence = re.sub(
            rf"\b{re.escape(word)}\b",
            "_____",
            example,
            flags=re.IGNORECASE
        )

        # ----------------------------------------------------
        # Nếu Oxford example không chứa word,
        # tạo câu fallback.
        # ----------------------------------------------------

        if blank_sentence == example:

            blank_sentence = (
                f"_____ "
                f"({meaning})"
            )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word,
            "word": word
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
            "opportunity",
            "challenge",
            "environment"
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
# 18. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Thời Điểm Vàng • 4 móc mỗi cấp • 6 dạng câu hỏi"
)

now = datetime.now()

due_count = sum(
    1
    for x in st.session_state.deck
    if x["next_review"] <= now
)


# ============================================================
# 19. MENU
# ============================================================

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
    format_func=lambda x: tab_labels[x],
    key="active_tab",
    horizontal=True,
    label_visibility="collapsed"
)

st.markdown("---")


# ============================================================
# 20. TAB ÔN TẬP
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

    # ========================================================
    # CHƯA CÓ TỪ
    # ========================================================

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang **🔍 Tra Từ Mới** "
            "để thêm từ."
        )

    # ========================================================
    # CHƯA ĐẾN GIỜ
    # ========================================================

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
            st.metric(
                "Móc",
                f"{next_item.get('hook', 0)}/4"
            )

        st.info(
            f"⏰ Còn khoảng "
            f"**{format_remaining(remaining)}**"
        )

        st.caption(
            f"📌 "
            f"{get_level_name(next_item['level'])}"
            f" • "
            f"{get_hook_name(next_item.get('hook', 0))}"
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

            var now =
                new Date().getTime();

            var diff =
                targetTime - now;

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

    # ========================================================
    # CÓ TỪ CẦN ÔN
    # ========================================================

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

                MochiVocab sẽ ưu tiên từ có cấp thấp
                trước và bắt đầu tính thời gian phản hồi
                ngay khi câu hỏi xuất hiện.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review"
            ):

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

            # =================================================
            # STOP
            # =================================================

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

            # =================================================
            # LEVEL / HOOK
            # =================================================

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
                hook / 4
            )

            col1, col2, col3 = st.columns(3)

            with col1:

                st.caption(
                    get_level_name(level)
                )

            with col2:

                st.caption(
                    f"📌 {hook}/4 móc"
                )

            with col3:

                st.caption(
                    f"Đã ôn: "
                    f"{item.get('review_count', 0)}"
                )

            current_interval = item.get(
                "interval",
                get_current_interval(
                    level,
                    hook
                )
            )

            st.caption(
                f"⏰ Khoảng ôn hiện tại: "
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
                        )
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # DẠNG 2 — FILL BLANK
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                st.caption(
                    "📖 Example ưu tiên từ Oxford"
                )

                st.info(
                    f'"{q_data.get("sentence")}"'
                )

                user_ans = st.text_input(
                    "Từ còn thiếu:",
                    key=f"fill_{item['id']}"
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
                        == item["word"].lower(),
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 3 — SPELLING
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
                    key=f"spell_{item['id']}"
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
                        == item["word"].lower(),
                        item["word"].upper()
                    )

            # =================================================
            # DẠNG 4 — CONTEXT
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

            # =================================================
            # DẠNG 5 — TRUE / FALSE
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
                        key=f"true_{item['id']}"
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
                        key=f"false_{item['id']}"
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
            # DẠNG 6 — MEANING CHOICE
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
# 21. TAB TRA TỪ
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

            if not data["success"]:

                st.error(
                    f"❌ Không tìm thấy "
                    f"**{word_input}**."
                )

                st.session_state.temp_word = None

            else:

                example = (
                    data.get(
                        "example",
                        ""
                    )
                    or
                    f"It is important to understand {word_input}."
                )

                st.session_state.temp_word = {

                    "word":
                        word_input,

                    "phonetic":
                        data.get(
                            "phonetic",
                            f"/{word_input}/"
                        ),

                    "meaning":
                        data.get(
                            "meaning",
                            word_input
                        ),

                    "example":
                        example,

                    "source":
                        data.get(
                            "source",
                            "Dictionary API"
                        ),

                    "definition_en":
                        data.get(
                            "definition_en",
                            ""
                        ),

                    "part_of_speech":
                        data.get(
                            "part_of_speech",
                            ""
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

        if data.get(
            "part_of_speech"
        ):

            st.caption(
                f"🏷️ "
                f"{data['part_of_speech']}"
            )

        st.write(
            f"👉 **Nghĩa:** "
            f"{data['meaning'].upper()}"
        )

        if data.get(
            "definition_en"
        ):

            st.write(
                f"📖 **Definition:** "
                f"{data['definition_en']}"
            )

        st.caption(
            f"💡 **Example:** "
            f"{data['example']}"
        )

        st.caption(
            f"📚 Nguồn: "
            f"**{data.get('source', 'Dictionary API')}**"
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

                        "id":
                            get_next_id(),

                        "word":
                            data["word"],

                        "phonetic":
                            data["phonetic"],

                        "meaning":
                            data["meaning"],

                        # Lưu example Oxford ngay từ đầu.
                        "example":
                            data["example"],

                        "source":
                            data.get(
                                "source",
                                "Dictionary API"
                            ),

                        "definition_en":
                            data.get(
                                "definition_en",
                                ""
                            ),

                        "part_of_speech":
                            data.get(
                                "part_of_speech",
                                ""
                            ),

                        # ------------------------------------
                        # HỆ THỐNG CẤP MỚI
                        # ------------------------------------

                        "level":
                            0,

                        "hook":
                            0,

                        "interval":
                            60,

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

                        "question_wrong_streak":
                            0,

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
                        "⏰ Móc đầu tiên: "
                        "**1 giờ**"
                    )

                    time.sleep(1)

                    st.rerun()


# ============================================================
# 22. TAB SỔ TAY
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

        # ====================================================
        # BẢNG GOLDEN TIME
        # ====================================================

        st.markdown(
            "### ⏰ Hệ thống Thời Điểm Vàng"
        )

        golden_table = []

        for level in range(
            MAX_LEVEL + 1
        ):

            intervals = GOLDEN_TIME[level]

            golden_table.append(
                {
                    "Cấp":
                        level,

                    "Móc 1":
                        format_interval(
                            intervals[0]
                        ),

                    "Móc 2":
                        format_interval(
                            intervals[1]
                        ),

                    "Móc 3":
                        format_interval(
                            intervals[2]
                        ),

                    "Móc 4":
                        format_interval(
                            intervals[3]
                        ),

                    "Trạng thái":
                        (
                            "🏆 Tối đa"
                            if level == 5
                            else "Đang tiến cấp"
                        )
                }
            )

        st.dataframe(
            golden_table,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        # ====================================================
        # WORD TABLE
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

            table_data.append(
                {

                    "Từ":
                        item["word"].upper(),

                    "Nghĩa":
                        item["meaning"],

                    "Cấp":
                        item["level"],

                    "Móc":
                        f"{item.get('hook', 0)}/4",

                    "Trạng thái":
                        get_level_name(
                            item["level"]
                        ),

                    "Khoảng ôn":
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
                }
            )

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

        # ====================================================
        # DELETE ALL
        # ====================================================

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
# 23. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • "
    "Dynamic Golden Time • "
    "4 Hooks / Level"
)
