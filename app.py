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
# ============================================================

# Mỗi cấp có 4 móc.
#
# Cấp 0:
#   Móc 1 = 1h
#   Móc 2 = 4h
#   Móc 3 = 12h
#   Móc 4 = 24h
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

GOLDEN_TIMES = {
    0: [60, 240, 720, 1440],
    1: [1500, 1680, 2160, 2880],
    2: [2940, 3120, 3600, 4320],
    3: [4380, 4560, 5040, 5760],
    4: [5820, 6000, 6480, 7200],
}

MAX_LEVEL = 4
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

    hours = minutes / 60

    if hours.is_integer():
        return f"{int(hours)} giờ"

    if hours < 24:
        return f"{hours:.1f} giờ"

    days = hours / 24

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
# 5. GOLDEN TIME UTILITIES
# ============================================================

def get_golden_interval(level, hook):
    """
    Lấy Golden Time dựa trên cấp + móc.

    level:
        0 -> 4

    hook:
        1 -> 4
    """

    level = max(0, min(int(level), MAX_LEVEL))
    hook = max(1, min(int(hook), HOOKS_PER_LEVEL))

    return GOLDEN_TIMES[level][hook - 1]


def get_level_name(level):
    names = {
        0: "🆕 Cấp 0 - Mới học",
        1: "🥉 Cấp 1 - Đang hình thành",
        2: "🥈 Cấp 2 - Đã nhớ",
        3: "🥇 Cấp 3 - Nhớ khá tốt",
        4: "💎 Cấp 4 - Nhớ lâu",
        5: "🏆 Cấp 5 - Ghi nhớ rất tốt"
    }

    return names.get(level, "🆕 Cấp 0 - Mới học")


def get_hook_name(hook):
    names = {
        1: "Móc 1/4",
        2: "Móc 2/4",
        3: "Móc 3/4",
        4: "Móc 4/4"
    }

    return names.get(hook, "Móc 1/4")


def get_progress_text(level, hook):
    return f"Cấp {level} • Móc {hook}/4"


# ============================================================
# 6. TIẾN / LÙI MÓC
# ============================================================

def move_hook_after_correct(item):
    """
    Trả lời đúng:

    Móc 1 -> Móc 2
    Móc 2 -> Móc 3
    Móc 3 -> Móc 4
    Móc 4 -> lên cấp mới, Móc 1

    Ví dụ:

    Cấp 0 - Móc 4
        ↓ đúng
    Cấp 1 - Móc 1
    """

    level = int(item.get("level", 0))
    hook = int(item.get("hook", 1))

    if hook < HOOKS_PER_LEVEL:
        hook += 1

    else:
        if level < MAX_LEVEL:
            level += 1
            hook = 1
        else:
            # Đã đạt cấp cao nhất
            level = MAX_LEVEL
            hook = HOOKS_PER_LEVEL

    item["level"] = level
    item["hook"] = hook

    return level, hook


def move_hook_after_wrong(item):
    """
    Trả lời sai:

    Móc 4 -> Móc 3
    Móc 3 -> Móc 2
    Móc 2 -> Móc 1
    Móc 1 -> cấp trước, Móc 4

    Ví dụ:

    Cấp 2 - Móc 1
        ↓ sai
    Cấp 1 - Móc 4
    """

    level = int(item.get("level", 0))
    hook = int(item.get("hook", 1))

    if hook > 1:
        hook -= 1

    else:
        if level > 0:
            level -= 1
            hook = HOOKS_PER_LEVEL
        else:
            level = 0
            hook = 1

    item["level"] = level
    item["hook"] = hook

    return level, hook


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
                # ------------------------------------------------

                item["hook"] = max(
                    1,
                    min(
                        int(item.get("hook", 1)),
                        HOOKS_PER_LEVEL
                    )
                )

                # ------------------------------------------------
                # INTERVAL
                # ------------------------------------------------

                item["interval"] = get_golden_interval(
                    item["level"],
                    item["hook"]
                )

                # ------------------------------------------------
                # STATISTICS
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
# 9. TIỆN ÍCH PHÁT ÂM
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
# 10. DỊCH
# ============================================================

def translate_single_text(text):

    if not text or not text.strip():
        return text

    try:

        url = (
            "https://translate.googleapis.com/"
            "translate_a/single?"
            "client=gtx"
            "&sl=en"
            "&tl=vi"
            "&dt=t"
            f"&q={urllib.parse.quote(text.strip())}"
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
                response.read().decode("utf-8")
            )

            return "".join(
                item[0]
                for item in data[0]
                if item[0]
            ).strip()

    except Exception:
        return text


# ============================================================
# 11. TRA TỪ
# ============================================================

def fetch_word_full_data_FAST(word):

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
            timeout=3
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

                        if definition.get(
                            "definition"
                        ):

                            meanings_raw.append({
                                "type": pos,
                                "en": definition[
                                    "definition"
                                ]
                            })

                        if definition.get(
                            "example"
                        ):

                            examples.append(
                                definition["example"]
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

    short_vn = translate_single_text(word)

    return {
        "success": True,
        "phonetic": phonetic,
        "short_vn": short_vn,
        "examples": examples
    }


def get_next_id():

    if not st.session_state.deck:
        return 1

    return max(
        int(x.get("id", 0))
        for x in st.session_state.deck
    ) + 1


# ============================================================
# 12. ONLINE EXAMPLE
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
            timeout=2
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

                        if definition.get(
                            "example"
                        ):
                            return definition[
                                "example"
                            ]

    except Exception:
        pass

    return None


# ============================================================
# 13. TẠO CÂU HỎI
# ============================================================

def prepare_review_question(item):

    # --------------------------------------------------------
    # KHÔNG CÒN AUDIO_CHOICE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EXAMPLE
    # --------------------------------------------------------

    if not example:

        online_example = fetch_online_word_data(
            word
        )

        example = (
            online_example
            if online_example
            else f"The word '{word}' is very important."
        )

    # --------------------------------------------------------
    # OTHER WORDS
    # --------------------------------------------------------

    deck_words = [
        x.get("word", "").strip()
        for x in st.session_state.get(
            "deck",
            []
        )
        if (
            x.get("word", "").strip()
            and
            x.get("word", "").strip().lower()
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
            and
            x.get("meaning", "").strip()
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

        blank_sentence = re.sub(
            re.escape(word),
            "_____",
            example,
            flags=re.IGNORECASE
        )

        if blank_sentence == example:

            blank_sentence = (
                f"{example} (_____)"
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

        is_true = random.choice([
            True,
            False
        ])

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

    # --------------------------------------------------------
    # RESPONSE TIME
    # --------------------------------------------------------

    response_time = max(
        0.1,
        time.time()
        - st.session_state.review_start_time
    )

    old_level = int(
        item.get("level", 0)
    )

    old_hook = int(
        item.get("hook", 1)
    )

    # ========================================================
    # ĐÚNG
    # ========================================================

    if is_correct:

        new_level, new_hook = (
            move_hook_after_correct(item)
        )

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

        if new_level > old_level:

            st.success(
                f"🎉 Đủ 4 móc! "
                f"Cấp độ: "
                f"**{old_level} → {new_level}**"
            )

            if new_level == MAX_LEVEL:

                st.balloons()

                st.success(
                    "🏆 Từ này đã đạt cấp cao nhất!"
                )

        else:

            st.info(
                f"📌 Tiến độ mới: "
                f"**Cấp {new_level} - "
                f"Móc {new_hook}/4**"
            )

    # ========================================================
    # SAI
    # ========================================================

    else:

        new_level, new_hook = (
            move_hook_after_wrong(item)
        )

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

        st.warning(
            f"📉 Tụt 1 móc: "
            f"Cấp {old_level} - Móc {old_hook}/4 "
            f"→ "
            f"Cấp {new_level} - Móc {new_hook}/4"
        )

    # ========================================================
    # THỐNG KÊ
    # ========================================================

    item["review_count"] = int(
        item.get("review_count", 0)
    ) + 1

    item["last_response_time"] = round(
        response_time,
        2
    )

    # ========================================================
    # GOLDEN TIME MỚI
    # ========================================================

    new_interval = get_golden_interval(
        item["level"],
        item["hook"]
    )

    item["interval"] = new_interval

    item["next_review"] = (
        datetime.now()
        + timedelta(
            minutes=new_interval
        )
    )

    st.info(
        f"⏰ Thời Điểm Vàng tiếp theo: "
        f"**{format_interval(new_interval)}**"
    )

    # ========================================================
    # SAVE
    # ========================================================

    save_deck()

    # ========================================================
    # SAI -> HỎI LẠI NGAY
    # ========================================================

    if not is_correct:

        time.sleep(0.8)

        # Giữ nguyên review_started
        # Giữ chính item hiện tại
        # Tạo câu hỏi hoàn toàn mới

        prepare_review_question(item)

    # ========================================================
    # ĐÚNG -> KẾT THÚC CÂU HIỆN TẠI
    # ========================================================

    else:

        st.session_state.review_item = None

        st.session_state.q_type = None

        st.session_state.q_data = {}

        time.sleep(0.8)

    st.rerun()


# ============================================================
# 15. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Thời Điểm Vàng • 4 móc mỗi cấp • "
    "Sai 1 lần = tụt 1 móc"
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
    # CHƯA CÓ TỪ ĐẾN GIỜ
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
                "Cấp",
                next_item["level"]
            )

        with col3:
            st.metric(
                "Móc",
                f"{next_item.get('hook', 1)}/4"
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

    # ========================================================
    # CÓ TỪ CẦN ÔN
    # ========================================================

    else:

        # ----------------------------------------------------
        # CHƯA BẮT ĐẦU
        # ----------------------------------------------------

        if not st.session_state.review_started:

            st.success(
                f"🔥 Có **{len(due_items)} từ** "
                f"đang đến Thời Điểm Vàng."
            )

            st.markdown("---")

            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                MochiVocab sẽ ưu tiên từ có
                **Cấp + Móc thấp nhất**.

                Trả lời đúng → tiến 1 móc.

                Trả lời sai → tụt 1 móc và
                **hỏi lại ngay bằng câu hỏi mới**.
                """
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review"
            ):

                candidates = sorted(
                    due_items,
                    key=lambda x: (
                        int(x.get("level", 0)),
                        int(x.get("hook", 1))
                    )
                )

                item = candidates[0]

                st.session_state.review_started = True

                prepare_review_question(item)

                st.rerun()

        # ----------------------------------------------------
        # ĐANG ÔN
        # ----------------------------------------------------

        else:

            current_item = (
                st.session_state.review_item
            )

            # ------------------------------------------------
            # CHƯA CÓ CÂU HỎI
            # ------------------------------------------------

            if current_item is None:

                # Refresh danh sách due
                now = datetime.now()

                due_items = [
                    x
                    for x in st.session_state.deck
                    if x["next_review"] <= now
                ]

                if not due_items:

                    st.session_state.review_started = False

                    st.rerun()

                candidates = sorted(
                    due_items,
                    key=lambda x: (
                        int(x.get("level", 0)),
                        int(x.get("hook", 1))
                    )
                )

                item = candidates[0]

                prepare_review_question(item)

                st.rerun()

            item = st.session_state.review_item

            q_type = st.session_state.q_type

            q_data = st.session_state.q_data

            # ------------------------------------------------
            # DỪNG
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
            # LEVEL + HOOK
            # ------------------------------------------------

            level = int(
                item.get("level", 0)
            )

            hook = int(
                item.get("hook", 1)
            )

            st.progress(
                hook / HOOKS_PER_LEVEL
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_level_name(level)
                )

                st.caption(
                    f"📌 {get_hook_name(hook)}"
                )

            with col2:

                st.caption(
                    f"Đã ôn: "
                    f"{item.get('review_count', 0)} lần"
                )

            current_interval = (
                get_golden_interval(
                    level,
                    hook
                )
            )

            st.caption(
                f"📐 Thời Điểm Vàng hiện tại: "
                f"**{format_interval(current_interval)}**"
            )

            st.markdown("---")

            # =================================================
            # DẠNG 1: CHỌN NGHĨA
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
            # DẠNG 2: ĐIỀN TỪ
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CÂU"
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
            # DẠNG 3: CHÍNH TẢ
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
            # DẠNG 4: NGỮ CẢNH
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
            # DẠNG 5: FLASHCARD TRUE/FALSE
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

            # =================================================
            # DẠNG 6: NGHĨA -> CHỌN TỪ
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
                        f"It is important to "
                        f"understand {word_input}."
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

        st.write(
            f"👉 **Nghĩa:** "
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

                        # ------------------------------------
                        # HỆ THỐNG MỚI
                        # ------------------------------------

                        "level": 0,

                        "hook": 1,

                        "interval": GOLDEN_TIMES[
                            0
                        ][0],

                        # ------------------------------------
                        # THỐNG KÊ
                        # ------------------------------------

                        "review_count": 0,

                        "correct_count": 0,

                        "wrong_count": 0,

                        "last_response_time": None,

                        "last_result": None,

                        # ------------------------------------
                        # ÔN NGAY
                        # ------------------------------------

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
                        "**Cấp 0 - Móc 1 - 1 giờ**."
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
            if (
                int(x.get("level", 0))
                >= MAX_LEVEL
                and
                int(x.get("hook", 1))
                >= HOOKS_PER_LEVEL
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
                "Đạt cấp cao nhất",
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
                +
                item.get("wrong_count", 0)
            )

            if accuracy_total > 0:

                accuracy_text = (
                    f"{(
                        item.get(
                            'correct_count',
                            0
                        )
                        /
                        accuracy_total
                        *
                        100
                    ):.0f}%"
                )

            else:

                accuracy_text = "—"

            level = int(
                item.get("level", 0)
            )

            hook = int(
                item.get("hook", 1)
            )

            interval = get_golden_interval(
                level,
                hook
            )

            table_data.append({

                "Từ":
                    item["word"].upper(),

                "Nghĩa":
                    item["meaning"],

                "Cấp":
                    level,

                "Móc":
                    f"{hook}/4",

                "Trạng thái":
                    get_level_name(level),

                "Golden Time":
                    format_interval(interval),

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
        # CHI TIẾT GOLDEN TIME
        # ====================================================

        with st.expander(
            "📐 Xem bảng Golden Time"
        ):

            st.write(
                "Mỗi cấp có 4 móc. "
                "Đúng → tiến 1 móc. "
                "Sai → lùi 1 móc."
            )

            golden_table = []

            for level in range(
                MAX_LEVEL + 1
            ):

                for hook in range(
                    1,
                    HOOKS_PER_LEVEL + 1
                ):

                    golden_table.append({

                        "Cấp":
                            level,

                        "Móc":
                            f"{hook}/4",

                        "Thời Điểm Vàng":
                            format_interval(
                                get_golden_interval(
                                    level,
                                    hook
                                )
                            )
                    })

            st.dataframe(
                golden_table,
                use_container_width=True,
                hide_index=True
            )

        # ====================================================
        # XÓA TOÀN BỘ
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
# 20. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • "
    "4 Hooks Golden Time"
)
