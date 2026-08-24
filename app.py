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
# 2. CẤU HÌNH GOLDEN TIME
# ============================================================

# Mỗi cấp có 4 móc.
#
# Cấp 0:
#   1h -> 4h -> 12h -> 24h
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
# Cấp 5:
#   Sau 120h tiếp tục giữ cấp 5.

GOLDEN_STEPS = {
    0: [60, 240, 720, 1440],
    1: [1500, 1680, 2160, 2880],
    2: [2940, 3120, 3600, 4320],
    3: [4380, 4560, 5040, 5760],
    4: [5820, 6000, 6480, 7200],
    5: [7200]
}

MAX_LEVEL = 5
STEPS_PER_LEVEL = 4


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
# 5. GOLDEN TIME - TÍNH MỐC HIỆN TẠI
# ============================================================

def get_step_index(item):
    """
    Trả về móc hiện tại:
    0 = chưa qua móc nào
    1 = đã qua móc 1
    2 = đã qua móc 2
    3 = đã qua móc 3
    4 = đã qua đủ 4 móc
    """

    step = int(item.get("step", 0))

    return max(0, min(step, STEPS_PER_LEVEL))


def get_current_target_minutes(item):
    """
    Lấy thời gian của móc hiện tại.
    """

    level = max(0, min(int(item.get("level", 0)), MAX_LEVEL))
    step = get_step_index(item)

    steps = GOLDEN_STEPS.get(level, GOLDEN_STEPS[0])

    if level == MAX_LEVEL:
        return steps[-1]

    if step >= STEPS_PER_LEVEL:
        return steps[-1]

    return steps[step]


def get_next_golden_minutes(item):
    """
    Thời gian ôn tiếp theo.
    """

    level = max(0, min(int(item.get("level", 0)), MAX_LEVEL))
    step = get_step_index(item)

    if level < MAX_LEVEL:
        steps = GOLDEN_STEPS[level]

        if step < STEPS_PER_LEVEL:
            return steps[step]

        return steps[-1]

    return GOLDEN_STEPS[MAX_LEVEL][-1]


def get_progress_text(item):
    level = int(item.get("level", 0))
    step = get_step_index(item)

    if level >= MAX_LEVEL:
        return "🏆 Cấp 5 • Ghi nhớ rất tốt"

    return f"📍 Cấp {level} • Móc {step}/4"


def get_level_name(level):
    names = {
        0: "🆕 Mới học",
        1: "🥉 Đang hình thành",
        2: "🥈 Đã nhớ",
        3: "🥇 Nhớ khá tốt",
        4: "💎 Nhớ lâu",
        5: "🏆 Ghi nhớ rất tốt"
    }

    return names.get(level, "🆕 Mới học")


# ============================================================
# 6. GOLDEN TIME - XỬ LÝ ĐÚNG / SAI
# ============================================================

def process_golden_result(item, is_correct):
    """
    Đúng:
        Móc 0 -> 1
        Móc 1 -> 2
        Móc 2 -> 3
        Móc 3 -> lên cấp mới, móc 0

    Sai:
        Rớt 1 móc.

        Ví dụ:
        móc 3 -> móc 2
        móc 2 -> móc 1
        móc 1 -> móc 0

        Nếu đang móc 0:
        - cấp > 0: rớt về cấp trước, móc 3
        - cấp 0: giữ cấp 0, móc 0
    """

    level = int(item.get("level", 0))
    step = int(item.get("step", 0))

    level = max(0, min(level, MAX_LEVEL))
    step = max(0, min(step, STEPS_PER_LEVEL))

    if is_correct:

        # CẤP 5
        if level >= MAX_LEVEL:
            return MAX_LEVEL, STEPS_PER_LEVEL

        # Chưa đủ 4 móc
        if step < STEPS_PER_LEVEL - 1:
            return level, step + 1

        # Đã hoàn thành móc 4 -> lên cấp
        return level + 1, 0

    else:

        # Sai ở móc > 0 -> rớt 1 móc
        if step > 0:
            return level, step - 1

        # Sai ở móc 0 -> rớt cấp
        if level > 0:
            return level - 1, STEPS_PER_LEVEL - 1

        # Cấp 0 móc 0 -> giữ nguyên
        return 0, 0


def get_interval_after_result(level, step):
    """
    Lấy khoảng ôn sau khi xử lý kết quả.
    """

    level = max(0, min(level, MAX_LEVEL))
    step = max(0, min(step, STEPS_PER_LEVEL))

    if level >= MAX_LEVEL:
        return GOLDEN_STEPS[MAX_LEVEL][-1]

    if step >= STEPS_PER_LEVEL:
        step = STEPS_PER_LEVEL - 1

    return GOLDEN_STEPS[level][step]


# ============================================================
# 7. LOAD LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:

    saved_data = local_storage.getItem("mochi_deck_data")

    if saved_data:
        try:
            items = json.loads(saved_data)
            cleaned_items = []

            for item in items:

                # ------------------------------------------------
                # next_review
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
                # level
                # ------------------------------------------------

                item["level"] = max(
                    0,
                    min(int(item.get("level", 0)), MAX_LEVEL)
                )

                # ------------------------------------------------
                # step
                # ------------------------------------------------

                if "step" not in item:

                    # Dữ liệu cũ không có step.
                    # Cho bắt đầu lại từ móc 0.
                    item["step"] = 0

                item["step"] = max(
                    0,
                    min(int(item.get("step", 0)), STEPS_PER_LEVEL)
                )

                # ------------------------------------------------
                # interval
                # ------------------------------------------------

                if "interval" not in item:
                    item["interval"] = get_next_golden_minutes(item)

                item["interval"] = int(
                    max(1, item["interval"])
                )

                # ------------------------------------------------
                # statistics
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
            copy_item["next_review"] = copy_item["next_review"].isoformat()

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
# 9. DỊCH ENGLISH DEFINITION -> VIETNAMESE
# ============================================================

def translate_definition_to_vietnamese(text):
    """
    QUAN TRỌNG:

    Không dịch trực tiếp tên từ nữa.

    Code cũ:
        translate("resilience")

    Code mới:
        lấy English definition:
        "the capacity to recover quickly from difficulties"

        rồi mới dịch definition sang tiếng Việt.
    """

    if not text or not text.strip():
        return ""

    text = text.strip()

    try:

        encoded = urllib.parse.quote(text)

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single"
            "?client=gtx"
            "&sl=en"
            "&tl=vi"
            "&dt=t"
            f"&q={encoded}"
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
                )

                if translated.strip():
                    return translated.strip()

    except Exception:
        pass

    return ""


# ============================================================
# 10. LẤY DỮ LIỆU TỪ DICTIONARY API
# ============================================================

def fetch_word_full_data_FAST(word):

    url = (
        "https://api.dictionaryapi.dev/"
        "api/v2/entries/en/"
        f"{urllib.parse.quote(word)}"
    )

    definitions = []
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

                # ================================================
                # LẤY PHONETIC
                # ================================================

                first = data[0]

                phonetic = (
                    first.get("phonetic")
                    or phonetic
                )

                if not phonetic:
                    for p in first.get("phonetics", []):
                        if p.get("text"):
                            phonetic = p["text"]
                            break

                # ================================================
                # LẤY DEFINITIONS
                # ================================================

                for meaning in first.get(
                    "meanings",
                    []
                ):

                    pos = meaning.get(
                        "partOfSpeech",
                        ""
                    )

                    for definition in meaning.get(
                        "definitions",
                        []
                    ):

                        english_definition = (
                            definition.get(
                                "definition",
                                ""
                            ).strip()
                        )

                        example = (
                            definition.get(
                                "example",
                                ""
                            ).strip()
                        )

                        if english_definition:

                            definitions.append({
                                "type": pos,
                                "en": english_definition
                            })

                        if example:
                            examples.append(example)

                        if len(definitions) >= 5:
                            break

                    if len(definitions) >= 5:
                        break

    except Exception:
        return {
            "success": False
        }

    if not definitions:
        return {
            "success": False
        }

    # ========================================================
    # DỊCH DEFINITION THAY VÌ DỊCH TÊN TỪ
    # ========================================================

    vietnamese_meanings = []

    for definition in definitions[:3]:

        vn = translate_definition_to_vietnamese(
            definition["en"]
        )

        if vn:
            vietnamese_meanings.append({
                "type": definition["type"],
                "en": definition["en"],
                "vi": vn
            })

    # Nếu dịch thất bại hoàn toàn
    if vietnamese_meanings:

        # Nghĩa đầu tiên là nghĩa chính
        short_vn = vietnamese_meanings[0]["vi"]

    else:

        # Không lấy tên từ làm nghĩa.
        # Nếu API dịch lỗi thì hiển thị English definition
        # để tránh đưa ra nghĩa tiếng Việt sai.
        short_vn = definitions[0]["en"]

    return {
        "success": True,
        "phonetic": phonetic,
        "short_vn": short_vn,
        "definitions": definitions,
        "vietnamese_meanings": vietnamese_meanings,
        "examples": examples
    }


# ============================================================
# 11. LẤY CÂU VÍ DỤ ONLINE
# ============================================================

def fetch_online_word_data(word):

    try:

        url = (
            "https://api.dictionaryapi.dev/"
            "api/v2/entries/en/"
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
# 13. TẠO CÂU HỎI
# ============================================================

def prepare_review_question(item):

    # BỎ AUDIO_CHOICE
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

    # ========================================================
    # QUAN TRỌNG:
    # Nếu từ chưa có example -> lấy example thật online.
    # Không còn:
    #
    # "The word 'xxx' is very important."
    #
    # ========================================================

    if not example:

        online_example = fetch_online_word_data(
            word
        )

        if online_example:
            example = online_example

            # cập nhật luôn vào deck
            item["example"] = example

        else:
            example = (
                f"The word {word} is "
                "used in everyday English."
            )

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

        if len(deck_meanings) > 0:

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
            "Kinh nghiệm"
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
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        # ----------------------------------------------------
        # Tìm đúng từ trong example.
        #
        # Ví dụ:
        #
        # "She showed great resilience after the accident."
        #
        # ->
        #
        # "She showed great _____ after the accident."
        # ----------------------------------------------------

        blank_sentence = re.sub(
            r"\b" + re.escape(word) + r"\b",
            "_____",
            example,
            flags=re.IGNORECASE
        )

        # Nếu example không chứa word
        if blank_sentence == example:

            # thử tìm biến thể đơn giản
            escaped_word = re.escape(word)

            blank_sentence = re.sub(
                escaped_word,
                "_____",
                example,
                flags=re.IGNORECASE
            )

        # Nếu vẫn không tìm được
        if blank_sentence == example:

            blank_sentence = (
                f"{example}\n\n"
                f"Điền từ thích hợp: _____"
            )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word,
            "word": word,
            "original_example": example
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
            "Kinh nghiệm"
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
            "adaptation"
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
# 14. XỬ LÝ ĐÁP ÁN
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

    old_step = int(
        item.get("step", 0)
    )

    # ========================================================
    # TÍNH LEVEL + MÓC MỚI
    # ========================================================

    new_level, new_step = process_golden_result(
        item,
        is_correct
    )

    new_interval = get_interval_after_result(
        new_level,
        new_step
    )

    # ========================================================
    # UPDATE ITEM
    # ========================================================

    item["level"] = new_level
    item["step"] = new_step
    item["interval"] = new_interval

    item["review_count"] = int(
        item.get(
            "review_count",
            0
        )
    ) + 1

    if is_correct:

        item["correct_count"] = int(
            item.get(
                "correct_count",
                0
            )
        ) + 1

    else:

        item["wrong_count"] = int(
            item.get(
                "wrong_count",
                0
            )
        ) + 1

    item["last_response_time"] = round(
        response_time,
        2
    )

    item["last_result"] = (
        "correct"
        if is_correct
        else "wrong"
    )

    item["next_review"] = (
        datetime.now()
        + timedelta(
            minutes=new_interval
        )
    )

    # ========================================================
    # HIỂN THỊ KẾT QUẢ
    # ========================================================

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
                f"🎉 Hoàn thành 4 móc! "
                f"Cấp độ: **{old_level} → {new_level}**"
            )

        else:

            st.success(
                f"📈 Móc: "
                f"**{old_step}/4 → {new_step}/4**"
            )

        st.info(
            f"⏰ Lần ôn tiếp theo: "
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

        if new_level < old_level:

            st.warning(
                f"📉 Rớt cấp: "
                f"**{old_level} → {new_level}**"
            )

        else:

            st.warning(
                f"📉 Rớt 1 móc: "
                f"**{old_step}/4 → {new_step}/4**"
            )

        st.info(
            f"🔄 Thời Điểm Vàng mới: "
            f"**{format_interval(new_interval)}**"
        )

    save_deck()

    # ========================================================
    # RESET CÂU HỎI
    #
    # Sai xong cũng tạo câu hỏi mới ở lần ôn kế tiếp.
    # ========================================================

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    time.sleep(1.2)

    st.rerun()


# ============================================================
# 15. HEADER
# ============================================================

st.title(
    "🍌 MochiVocab"
)

st.caption(
    "Dynamic Golden Time • 4 móc mỗi cấp"
)

now = datetime.now()

due_count = sum(
    1
    for x in st.session_state.deck
    if x["next_review"] <= now
)


# ============================================================
# 16. MENU
# ============================================================

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
# 17. TAB ÔN TẬP
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
    # KHÔNG CÓ TỪ
    # ========================================================

    if not st.session_state.deck:

        st.warning(
            "📚 Sổ tay đang trống."
        )

        st.write(
            "Hãy sang **🔍 Tra Từ Mới** để thêm từ."
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
                    days +
                    " ngày " +
                    hours +
                    ":" +
                    minutes +
                    ":" +
                    seconds;

            }} else {{

                element.innerHTML =
                    hours +
                    ":" +
                    minutes +
                    ":" +
                    seconds;
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
                "đang đến Thời Điểm Vàng."
            )

            st.markdown("---")

            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                MochiVocab sẽ ưu tiên từ ở cấp thấp
                và bắt đầu tính thời gian phản hồi.
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
            # LEVEL / STEP
            # =================================================

            level = int(
                item.get("level", 0)
            )

            step = int(
                item.get("step", 0)
            )

            if level >= MAX_LEVEL:
                progress_value = 1.0
            else:
                progress_value = step / 4

            st.progress(
                progress_value
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(level)
                )

            with col2:

                st.caption(
                    f"Móc: **{step}/4**"
                )

            current_interval = (
                item.get(
                    "interval",
                    get_next_golden_minutes(item)
                )
            )

            st.caption(
                f"📐 Khoảng ôn hiện tại: "
                f"**{format_interval(current_interval)}**"
            )

            st.caption(
                get_progress_text(item)
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
            # DẠNG 2 - FILL BLANK
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                st.caption(
                    "💡 Câu ví dụ được lấy từ "
                    "Dictionary API."
                )

                st.info(
                    f"**{q_data.get('sentence', '')}**"
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
            # DẠNG 3 - SPELLING
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
            # DẠNG 4 - CONTEXT
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
                        )
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"]
                        )

            # =================================================
            # DẠNG 5 - TRUE FALSE
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
            # DẠNG 6 - MEANING CHOICE
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
# 18. TAB TRA TỪ
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
                        f"The word "
                        f"{word_input} "
                        "is used in English."
                    )
                )

                st.session_state.temp_word = {
                    "word": word_input,
                    "phonetic": data["phonetic"],
                    "meaning": data["short_vn"],
                    "example": example,
                    "definitions": data.get(
                        "definitions",
                        []
                    ),
                    "vietnamese_meanings": data.get(
                        "vietnamese_meanings",
                        []
                    )
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
            f"{data['meaning'].upper()}"
        )

        st.caption(
            f"💡 Ví dụ: "
            f"{data['example']}"
        )

        # ====================================================
        # HIỂN THỊ THÊM ĐỊNH NGHĨA
        # ====================================================

        vietnamese_meanings = data.get(
            "vietnamese_meanings",
            []
        )

        if len(vietnamese_meanings) > 1:

            st.markdown(
                "#### 📖 Một số nghĩa khác"
            )

            for meaning_data in vietnamese_meanings[1:]:

                pos = meaning_data.get(
                    "type",
                    ""
                )

                vi = meaning_data.get(
                    "vi",
                    ""
                )

                if pos:

                    st.write(
                        f"- **{pos}**: {vi}"
                    )

                else:

                    st.write(
                        f"- {vi}"
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

                        # Golden Time
                        "level": 0,
                        "step": 0,
                        "interval": 60,

                        # Statistics
                        "review_count": 0,
                        "correct_count": 0,
                        "wrong_count": 0,

                        "last_response_time": None,
                        "last_result": None,

                        # Ôn ngay
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
                        "⏰ Từ mới sẽ được ôn ngay."
                    )

                    time.sleep(1)

                    st.rerun()


# ============================================================
# 19. TAB SỔ TAY
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

                status = "🔥 Sẵn sàng ôn!"

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

            table_data.append({

                "Từ":
                    item["word"].upper(),

                "Nghĩa":
                    item["meaning"],

                "Cấp":
                    item["level"],

                "Móc":
                    f"{item.get('step', 0)}/4",

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
            })

        st.dataframe(
            table_data,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("---")

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
# 20. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • "
    "Dynamic Golden Time • "
    "4 Mốc / Cấp"
)
