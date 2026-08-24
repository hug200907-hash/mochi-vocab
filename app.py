import json
import random
import time
import urllib.parse
import urllib.request
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
# 2. HỆ THỐNG CẤP & MỐC
# ============================================================
#
# Cấp 0:
#   - Chỉ dành cho từ mới
#   - 0h
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
# checkpoint:
#   Cấp 0: 0
#   Các cấp 1-5: 1 -> 4
#
# ============================================================

LEVEL_INTERVALS = {
    0: [0],
    1: [1, 4, 12, 24],
    2: [25, 28, 36, 48],
    3: [49, 52, 60, 72],
    4: [73, 76, 84, 96],
    5: [97, 100, 108, 120],
}

MAX_LEVEL = 5

VERY_FAST = 3
FAST = 6
NORMAL = 12
SLOW = 25


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

def format_interval(hours):
    hours = float(hours)

    if hours == 0:
        return "0 giờ"

    if hours < 1:
        return f"{int(hours * 60)} phút"

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
# 5. THÔNG TIN CẤP / MỐC
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


def get_checkpoint_name(level, checkpoint):
    if level == 0:
        return "Mốc 0 — Từ mới"

    return f"Mốc {checkpoint}/4"


def get_current_interval(level, checkpoint):
    level = max(0, min(int(level), MAX_LEVEL))

    if level == 0:
        return 0

    checkpoint = max(1, min(int(checkpoint), 4))

    return LEVEL_INTERVALS[level][checkpoint - 1]


def get_position_text(item):
    level = int(item.get("level", 0))
    checkpoint = int(item.get("checkpoint", 0))

    if level == 0:
        return "Cấp 0 • Mốc 0 • 0 giờ"

    interval = get_current_interval(level, checkpoint)

    return (
        f"Cấp {level} • Mốc {checkpoint}/4 "
        f"• {format_interval(interval)}"
    )


# ============================================================
# 6. TÍNH TỐC ĐỘ
# ============================================================

def calculate_speed_factor(response_time):
    if response_time <= VERY_FAST:
        return 1.25

    if response_time <= FAST:
        return 1.15

    if response_time <= NORMAL:
        return 1.00

    if response_time <= SLOW:
        return 0.85

    return 0.70


# ============================================================
# 7. TÍNH ĐỘ CHÍNH XÁC
# ============================================================

def calculate_accuracy_factor(item):
    correct = int(item.get("correct_count", 0))
    wrong = int(item.get("wrong_count", 0))

    total = correct + wrong

    if total == 0:
        return 1.0

    accuracy = correct / total

    if accuracy >= 0.95:
        return 1.15

    if accuracy >= 0.85:
        return 1.08

    if accuracy >= 0.70:
        return 1.00

    if accuracy >= 0.50:
        return 0.90

    return 0.75


# ============================================================
# 8. TÍNH MỐC TIẾP THEO
# ============================================================

def move_to_next_checkpoint(item, response_time):
    """
    Trả lời đúng:

    Cấp 0 / Mốc 0
        -> Cấp 1 / Mốc 1

    Cấp 1 / Mốc 1
        -> Cấp 1 / Mốc 2

    Cấp 1 / Mốc 4
        -> Cấp 2 / Mốc 1

    ...

    Cấp 5 / Mốc 4
        -> vẫn Cấp 5 / Mốc 4
    """

    level = int(item.get("level", 0))
    checkpoint = int(item.get("checkpoint", 0))

    # -----------------------------------------
    # TỪ MỚI: 0 -> CẤP 1 MỐC 1
    # -----------------------------------------

    if level == 0:
        return 1, 1

    # -----------------------------------------
    # CHƯA ĐẾN MỐC CUỐI
    # -----------------------------------------

    if checkpoint < 4:
        return level, checkpoint + 1

    # -----------------------------------------
    # ĐÃ ĐỦ 4 MỐC
    # LÊN CẤP
    # -----------------------------------------

    if level < MAX_LEVEL:
        return level + 1, 1

    # -----------------------------------------
    # CẤP 5 MỐC 4 = CAO NHẤT
    # -----------------------------------------

    return 5, 4


# ============================================================
# 9. TÍNH MỐC KHI TRẢ LỜI SAI
# ============================================================

def move_to_previous_checkpoint(item):
    """
    Trả lời sai:

    Cấp 1 / Mốc 4 -> Cấp 1 / Mốc 3
    Cấp 1 / Mốc 3 -> Cấp 1 / Mốc 2
    Cấp 1 / Mốc 2 -> Cấp 1 / Mốc 1
    Cấp 1 / Mốc 1 -> CẤP 1 / MỐC 1

    KHÔNG BAO GIỜ:
        Cấp 1 / Mốc 1 -> Cấp 0

    Từ mới:
        Cấp 0 / Mốc 0 -> Cấp 0 / Mốc 0
    """

    level = int(item.get("level", 0))
    checkpoint = int(item.get("checkpoint", 0))

    # Từ mới sai vẫn là từ mới
    if level == 0:
        return 0, 0

    # Mốc 1 không tụt về cấp 0
    if checkpoint <= 1:
        return level, 1

    # Lùi 1 mốc trong cùng cấp
    return level, checkpoint - 1


# ============================================================
# 10. TÍNH MỐC SAU KHI TRẢ LỜI
# ============================================================

def calculate_new_position(item, is_correct, response_time):
    if is_correct:
        return move_to_next_checkpoint(item, response_time)

    return move_to_previous_checkpoint(item)


# ============================================================
# 11. LOAD & SAVE LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:

    saved_data = local_storage.getItem("mochi_deck_data")

    if saved_data:
        try:
            items = json.loads(saved_data)

            cleaned_items = []

            for item in items:

                # -------------------------------
                # ID
                # -------------------------------

                item["id"] = int(item.get("id", len(cleaned_items) + 1))

                # -------------------------------
                # LEVEL
                # -------------------------------

                item["level"] = max(
                    0,
                    min(
                        int(item.get("level", 0)),
                        MAX_LEVEL
                    )
                )

                # -------------------------------
                # CHECKPOINT
                # -------------------------------

                if item["level"] == 0:
                    item["checkpoint"] = 0
                else:
                    item["checkpoint"] = max(
                        1,
                        min(
                            int(item.get("checkpoint", 1)),
                            4
                        )
                    )

                # -------------------------------
                # STATS
                # -------------------------------

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

                # -------------------------------
                # INTERVAL
                # -------------------------------

                item["interval"] = get_current_interval(
                    item["level"],
                    item["checkpoint"]
                )

                # -------------------------------
                # NEXT REVIEW
                # -------------------------------

                next_review = item.get("next_review")

                if isinstance(next_review, str):
                    try:
                        next_review = datetime.fromisoformat(
                            next_review
                        )
                    except Exception:
                        next_review = datetime.now()

                if not isinstance(next_review, datetime):
                    next_review = datetime.now()

                item["next_review"] = next_review

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
# 12. PHÁT ÂM
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
# 13. DỊCH ANH -> VIỆT
# ============================================================

def translate_single_text(text):

    if not text or not text.strip():
        return text

    try:

        encoded = urllib.parse.quote(
            text.strip()
        )

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
            f"?client=gtx&sl=en&tl=vi&dt=t&q={encoded}"
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

            result = ""

            for item in data[0]:

                if item and item[0]:
                    result += item[0]

            result = result.strip()

            if result:
                return result

    except Exception:
        pass

    return text


# ============================================================
# 14. TRA TỪ DICTIONARY API
# ============================================================

def fetch_dictionary_data(word):

    url = (
        "https://api.dictionaryapi.dev/"
        "api/v2/entries/en/"
        f"{urllib.parse.quote(word)}"
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
                response.read().decode("utf-8")
            )

            if not isinstance(data, list) or not data:
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
                        examples.append(example)

            return {
                "phonetic": phonetic,
                "examples": examples
            }

    except Exception:
        return None


# ============================================================
# 15. TRA VÍ DỤ ONLINE
# ============================================================

def fetch_online_word_data(word):

    data = fetch_dictionary_data(word)

    if data and data.get("examples"):
        return data["examples"][0]

    return None


# ============================================================
# 16. TRA FULL DATA
# ============================================================

def fetch_word_full_data_FAST(word):

    data = fetch_dictionary_data(word)

    if not data:
        return {
            "success": False
        }

    # Dịch chính TỪ TIẾNG ANH sang TIẾNG VIỆT
    short_vn = translate_single_text(word)

    examples = data.get(
        "examples",
        []
    )

    return {
        "success": True,
        "phonetic": data.get(
            "phonetic",
            f"/{word}/"
        ),
        "short_vn": short_vn,
        "examples": examples
    }


# ============================================================
# 17. GET ID
# ============================================================

def get_next_id():

    if not st.session_state.deck:
        return 1

    return max(
        int(x.get("id", 0))
        for x in st.session_state.deck
    ) + 1


# ============================================================
# 18. XỬ LÝ ĐÁP ÁN
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

    old_checkpoint = int(
        item.get("checkpoint", 0)
    )

    old_position = (
        old_level,
        old_checkpoint
    )

    # -------------------------------
    # TÍNH VỊ TRÍ MỚI
    # -------------------------------

    new_level, new_checkpoint = (
        calculate_new_position(
            item,
            is_correct,
            response_time
        )
    )

    # -------------------------------
    # INTERVAL MỚI
    # -------------------------------

    new_interval = get_current_interval(
        new_level,
        new_checkpoint
    )

    # -------------------------------
    # UPDATE ITEM
    # -------------------------------

    item["level"] = new_level
    item["checkpoint"] = new_checkpoint
    item["interval"] = new_interval

    item["review_count"] = int(
        item.get("review_count", 0)
    ) + 1

    if is_correct:

        item["correct_count"] = int(
            item.get("correct_count", 0)
        ) + 1

        item["last_result"] = "correct"

    else:

        item["wrong_count"] = int(
            item.get("wrong_count", 0)
        ) + 1

        item["last_result"] = "wrong"

    item["last_response_time"] = round(
        response_time,
        2
    )

    # -------------------------------
    # THỜI ĐIỂM ÔN TIẾP
    # -------------------------------

    if new_interval <= 0:

        item["next_review"] = datetime.now()

    else:

        item["next_review"] = (
            datetime.now()
            + timedelta(
                hours=new_interval
            )
        )

    # ========================================================
    # HIỂN THỊ KẾT QUẢ
    # ========================================================

    if is_correct:

        st.success("✨ Chính xác!")

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        if new_level != old_level:

            st.success(
                f"📈 Lên Cấp "
                f"**{old_level} → {new_level}**"
            )

        elif new_checkpoint != old_checkpoint:

            st.success(
                f"📈 Tiến lên "
                f"**Mốc {new_checkpoint}/4**"
            )

        else:

            st.info(
                "🏆 Đã ở mốc cao nhất!"
            )

        if new_level == 0:

            st.info(
                "🆕 Từ mới vẫn ở Cấp 0."
            )

        else:

            st.info(
                f"🧠 Mốc mới: "
                f"**{format_interval(new_interval)}**"
            )

        if new_level == 5 and new_checkpoint == 4:

            st.balloons()

            st.success(
                "🏆 Từ này đã đạt "
                "Cấp 5 - Mốc 4!"
            )

    else:

        st.error(
            "❌ Chưa chính xác."
        )

        st.warning(
            f"Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        if old_level == 0:

            st.info(
                "🆕 Từ mới sai nhưng "
                "**vẫn giữ Cấp 0 / Mốc 0**."
            )

        elif old_checkpoint == 1:

            st.warning(
                f"📉 Sai tại Mốc 1 nên "
                f"vẫn giữ **Cấp {old_level} / Mốc 1**."
            )

        else:

            st.warning(
                f"📉 Mốc: "
                f"**{old_checkpoint} → {new_checkpoint}**"
            )

        if new_level == 0:

            st.info(
                "🔄 Từ mới sẽ được hỏi lại ngay."
            )

        else:

            st.info(
                f"🔄 Mốc mới: "
                f"**{format_interval(new_interval)}**"
            )

    save_deck()

    # ========================================================
    # QUAN TRỌNG:
    # SAU KHI TRẢ LỜI XONG, XÓA CÂU HỎI CŨ.
    # LẦN RERUN TIẾP THEO SẼ TẠO CÂU HỎI MỚI.
    # ========================================================

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    time.sleep(0.8)

    st.rerun()


# ============================================================
# 19. TẠO CÂU HỎI
# ============================================================

def prepare_review_question(item):

    # Bỏ AUDIO_CHOICE
    q_types = [
        "CHOICE_MEANING",
        "FILL_BLANK",
        "SPELLING",
        "CONTEXT_MATCH",
        "FLASHCARD_TRUE_FALSE",
        "MEANING_CHOICE"
    ]

    chosen_q = random.choice(q_types)

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

    # --------------------------------------------------------
    # NẾU KHÔNG CÓ VÍ DỤ THÌ TRA ONLINE
    # --------------------------------------------------------

    if not example:

        online_example = (
            fetch_online_word_data(word)
        )

        if online_example:
            example = online_example

        else:
            example = (
                f"It is important to "
                f"understand {word}."
            )

    # --------------------------------------------------------
    # CÁC TỪ KHÁC
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
            "Sự thay đổi",
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

        # Tìm chính xác từ trong câu
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

        # Nếu câu không chứa từ,
        # thử tạo câu hỏi từ example
        if blank_sentence == example:

            blank_sentence = (
                f"{example}\n\n"
                f"👉 Từ còn thiếu: _____"
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
# 20. RESET ALL
# ============================================================

def reset_all_words():

    for item in st.session_state.deck:

        item["level"] = 0
        item["checkpoint"] = 0
        item["interval"] = 0

        item["review_count"] = 0
        item["correct_count"] = 0
        item["wrong_count"] = 0

        item["last_response_time"] = None
        item["last_result"] = None

        item["next_review"] = datetime.now()

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}
    st.session_state.review_started = False
    st.session_state.review_start_time = 0

    save_deck()


# ============================================================
# 21. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Thời Điểm Vàng • Hệ thống 5 cấp × 4 mốc"
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
        if x["next_review"] <= now
    ]

    # --------------------------------------------------------
    # CHƯA CÓ TỪ
    # --------------------------------------------------------

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang **🔍 Tra Từ Mới** để thêm từ."
        )

    # --------------------------------------------------------
    # KHÔNG CÓ TỪ ĐẾN HẠN
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
                Math.floor(totalSeconds / 86400);

            totalSeconds %= 86400;

            var hours =
                Math.floor(totalSeconds / 3600);

            totalSeconds %= 3600;

            var minutes =
                Math.floor(totalSeconds / 60);

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
    # CÓ TỪ ĐẾN HẠN
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

                MochiVocab sẽ chọn từ đến hạn và
                bắt đầu tính thời gian phản hồi.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review"
            ):

                # Ưu tiên từ có cấp thấp hơn
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

        # ----------------------------------------------------
        # ĐANG ÔN
        # ----------------------------------------------------

        else:

            current_item = (
                st.session_state.review_item
            )

            # Sau khi trả lời, tạo câu hỏi mới
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
            # STATUS
            # ------------------------------------------------

            level = int(
                item.get("level", 0)
            )

            checkpoint = int(
                item.get("checkpoint", 0)
            )

            if level == 0:

                st.progress(0)

            else:

                progress_value = (
                    (
                        (level - 1) * 4
                        + checkpoint
                    )
                    / 20
                )

                st.progress(
                    min(
                        1.0,
                        max(
                            0.0,
                            progress_value
                        )
                    )
                )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(level)
                )

                st.caption(
                    get_checkpoint_name(
                        level,
                        checkpoint
                    )
                )

            with col2:

                st.caption(
                    f"Đã ôn: "
                    f"{item.get('review_count', 0)} lần"
                )

            current_interval = (
                get_current_interval(
                    level,
                    checkpoint
                )
            )

            st.caption(
                f"📐 Mốc hiện tại: "
                f"**{format_interval(current_interval)}**"
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

            # =================================================
            # CÂU 2
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                st.info(
                    q_data.get(
                        "sentence",
                        ""
                    )
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
            # CÂU 3
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
                        )
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
            # CÂU 6
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
# 23. TAB TRA TỪ
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

                    "phonetic": data[
                        "phonetic"
                    ],

                    "meaning": data[
                        "short_vn"
                    ],

                    "example": example
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
            f"{data['meaning'].upper()}"
        )

        st.caption(
            f"💡 Ví dụ: {data['example']}"
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

                        "phonetic": data[
                            "phonetic"
                        ],

                        "meaning": data[
                            "meaning"
                        ],

                        "example": data[
                            "example"
                        ],

                        # ==========================
                        # TỪ MỚI = CẤP 0
                        # ==========================

                        "level": 0,

                        "checkpoint": 0,

                        "interval": 0,

                        "review_count": 0,

                        "correct_count": 0,

                        "wrong_count": 0,

                        "last_response_time": None,

                        "last_result": None,

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
                        "🆕 Từ mới bắt đầu "
                        "**Cấp 0 / Mốc 0 / 0 giờ**."
                    )

                    time.sleep(1)

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
            if x["next_review"]
            <= datetime.now()
        )

        mastered = sum(
            1
            for x in st.session_state.deck
            if (
                x["level"] == 5
                and x["checkpoint"] == 4
            )
        )

        new_words = sum(
            1
            for x in st.session_state.deck
            if x["level"] == 0
        )

        col1, col2, col3, col4 = st.columns(4)

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
                "Từ mới",
                new_words
            )

        with col4:

            st.metric(
                "Max",
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

                status = "🔥 Sẵn sàng ôn!"

            else:

                status = (
                    f"⏳ "
                    f"{format_remaining(remaining)}"
                )

            accuracy_total = (
                item.get("correct_count", 0)
                + item.get("wrong_count", 0)
            )

            # FIX LỖI ACCURACY
            if accuracy_total > 0:

                accuracy_text = {
                    f"{("
                    f"item.get('correct_count', 0)"
                    f" / accuracy_total * 100"
                    f"):.0f}%"
                )

            else:

                accuracy_text = "—"

            level = int(
                item.get("level", 0)
            )

            checkpoint = int(
                item.get("checkpoint", 0)
            )

            table_data.append({

                "Từ":
                    item["word"].upper(),

                "Nghĩa":
                    item["meaning"],

                "Cấp":
                    level,

                "Mốc":
                    (
                        "Mốc 0"
                        if level == 0
                        else f"{checkpoint}/4"
                    ),

                "Trạng thái":
                    get_level_name(level),

                "Thời Điểm":
                    format_interval(
                        get_current_interval(
                            level,
                            checkpoint
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

        # ====================================================
        # HIỂN THỊ HỆ THỐNG
        # ====================================================

        st.markdown(
            "### 🧠 Hệ thống Thời Điểm Vàng"
        )

        st.write(
            """
            - 🆕 **Cấp 0:** 0 giờ — chỉ dành cho từ mới
            - 🥉 **Cấp 1:** 1h → 4h → 12h → 24h
            - 🥈 **Cấp 2:** 25h → 28h → 36h → 48h
            - 🥇 **Cấp 3:** 49h → 52h → 60h → 72h
            - 💎 **Cấp 4:** 73h → 76h → 84h → 96h
            - 🏆 **Cấp 5:** 97h → 100h → 108h → 120h
            """
        )

        st.info(
            "❗ Nếu sai ở Mốc 1, từ vẫn giữ Mốc 1 "
            "của cấp hiện tại, không tụt về Cấp 0."
        )

        st.markdown("---")

        # ====================================================
        # RESET ALL
        # ====================================================

        st.markdown(
            "### 🔄 Đặt lại toàn bộ tiến độ"
        )

        st.warning(
            "Thao tác này sẽ đưa toàn bộ từ về "
            "**Cấp 0 / Mốc 0 / 0 giờ** và xóa "
            "thống kê số lần đúng/sai."
        )

        if st.button(
            "🔄 RESET ALL VỀ CẤP 0",
            type="secondary",
            use_container_width=True,
            key="reset_all_words"
        ):

            reset_all_words()

            st.success(
                "✅ Đã đưa toàn bộ từ về "
                "**Cấp 0 / Mốc 0 / 0 giờ**."
            )

            time.sleep(0.5)

            st.rerun()

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
# 25. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • Dynamic Golden Time"
)
