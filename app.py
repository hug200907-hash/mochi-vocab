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
# 2. CẤU HÌNH THUẬT TOÁN THỜI ĐIỂM VÀNG
# ============================================================

MIN_INTERVAL = 5

MAX_INTERVAL = 60 * 24 * 60
# = 60 ngày


LEVEL_FACTORS = {
    0: 1.00,
    1: 1.25,
    2: 1.50,
    3: 1.75,
    4: 2.00,
    5: 2.25
}


CORRECT_FACTOR = 2.20
WRONG_FACTOR = 0.30


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

# ------------------------------------------------------------
# MỚI:
# Chỉ bắt đầu phiên ôn khi người dùng bấm nút
# ------------------------------------------------------------

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
# 5. TÍNH HỆ SỐ TỐC ĐỘ
# ============================================================

def calculate_speed_factor(response_time):

    if response_time <= VERY_FAST:

        return 1.25

    elif response_time <= FAST:

        return 1.15

    elif response_time <= NORMAL:

        return 1.00

    elif response_time <= SLOW:

        return 0.85

    else:

        return 0.70


# ============================================================
# 6. TÍNH HỆ SỐ ĐỘ KHÓ DỰA TRÊN LỊCH SỬ
# ============================================================

def calculate_accuracy_factor(item):

    correct = item.get(
        "correct_count",
        0
    )

    wrong = item.get(
        "wrong_count",
        0
    )

    total = correct + wrong

    if total == 0:
        return 1.0

    accuracy = correct / total

    if accuracy >= 0.95:
        return 1.15

    elif accuracy >= 0.85:
        return 1.08

    elif accuracy >= 0.70:
        return 1.00

    elif accuracy >= 0.50:
        return 0.90

    else:
        return 0.75


# ============================================================
# 7. TÍNH THỜI ĐIỂM VÀNG
# ============================================================

def calculate_golden_interval(
    item,
    is_correct,
    response_time
):

    old_interval = float(
        item.get(
            "interval",
            5
        )
    )

    old_level = int(
        item.get(
            "level",
            0
        )
    )

    if old_interval <= 0:
        old_interval = 5


    # ========================================================
    # TRẢ LỜI SAI
    # ========================================================

    if not is_correct:

        new_interval = (
            old_interval
            * WRONG_FACTOR
        )

        new_interval = max(
            MIN_INTERVAL,
            new_interval
        )

        return int(
            round(new_interval)
        )


    # ========================================================
    # TRẢ LỜI ĐÚNG
    # ========================================================

    level_factor = LEVEL_FACTORS.get(
        old_level,
        1.0
    )

    speed_factor = calculate_speed_factor(
        response_time
    )

    accuracy_factor = calculate_accuracy_factor(
        item
    )


    # --------------------------------------------------------
    # Từ mới
    # --------------------------------------------------------

    if item.get("review_count", 0) == 0:

        base_interval = 10

    else:

        base_interval = old_interval


    # --------------------------------------------------------
    # Công thức chính
    # --------------------------------------------------------

    new_interval = (
        base_interval
        * CORRECT_FACTOR
        * level_factor
        * speed_factor
        * accuracy_factor
    )


    # --------------------------------------------------------
    # Giảm tốc độ tăng ở khoảng dài
    # --------------------------------------------------------

    if old_interval >= 10080:
        new_interval *= 0.75

    if old_interval >= 43200:
        new_interval *= 0.60


    # --------------------------------------------------------
    # Giới hạn
    # --------------------------------------------------------

    new_interval = max(
        MIN_INTERVAL,
        new_interval
    )

    new_interval = min(
        MAX_INTERVAL,
        new_interval
    )


    return int(
        round(new_interval)
    )


# ============================================================
# 8. TÍNH CẤP ĐỘ
# ============================================================

def calculate_level(
    old_level,
    is_correct,
    response_time
):

    old_level = max(
        0,
        min(old_level, 5)
    )

    if is_correct:

        if response_time <= VERY_FAST:

            increase = 1

        elif response_time <= NORMAL:

            increase = 1

        else:

            increase = 0

        new_level = min(
            5,
            old_level + increase
        )

    else:

        new_level = max(
            0,
            old_level - 1
        )

    return new_level


# ============================================================
# 9. MÔ TẢ CẤP ĐỘ
# ============================================================

def get_level_name(level):

    names = {

        0: "🆕 Mới học",

        1: "🥉 Đang hình thành",

        2: "🥈 Đã nhớ",

        3: "🥇 Nhớ khá tốt",

        4: "💎 Nhớ lâu",

        5: "🏆 Ghi nhớ rất tốt"

    }

    return names.get(
        level,
        "Mới học"
    )


# ============================================================
# 10. LOAD LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:

    saved_data = local_storage.getItem(
        "mochi_deck_data"
    )

    if saved_data:

        try:

            items = json.loads(
                saved_data
            )

            cleaned_items = []

            for item in items:

                if "next_review" not in item:

                    item["next_review"] = (
                        datetime.now()
                    )

                if isinstance(
                    item["next_review"],
                    str
                ):

                    item["next_review"] = (
                        datetime.fromisoformat(
                            item["next_review"]
                        )
                    )


                # ------------------------------------------------
                # Migration dữ liệu cũ
                # ------------------------------------------------

                item["level"] = max(
                    0,
                    min(
                        int(
                            item.get(
                                "level",
                                0
                            )
                        ),
                        5
                    )
                )


                if "interval" not in item:

                    remaining = (
                        item["next_review"]
                        - datetime.now()
                    ).total_seconds() / 60

                    item["interval"] = max(
                        MIN_INTERVAL,
                        min(
                            MAX_INTERVAL,
                            remaining
                        )
                    )


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

                cleaned_items.append(
                    item
                )


            st.session_state.deck = (
                cleaned_items
            )

        except Exception:

            st.session_state.deck = []


    st.session_state.data_loaded = True


# ============================================================
# 11. SAVE LOCAL STORAGE
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
                copy_item[
                    "next_review"
                ].isoformat()
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

    var msg =
        new SpeechSynthesisUtterance(
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
# 13. DỊCH
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
                response.read().decode(
                    "utf-8"
                )
            )

            translated = "".join(
                item[0]
                for item in data[0]
                if item[0]
            )

            return translated.strip()

    except Exception:

        return text


# ============================================================
# 14. TRA TỪ
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
            timeout=3
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

                            meanings_raw.append(
                                {
                                    "type": pos,
                                    "en": definition[
                                        "definition"
                                    ]
                                }
                            )


                        if definition.get(
                            "example"
                        ):

                            examples.append(
                                definition[
                                    "example"
                                ]
                            )


                        if len(
                            meanings_raw
                        ) >= 3:

                            break


                    if len(
                        meanings_raw
                    ) >= 3:

                        break


    except Exception:

        pass


    if not meanings_raw:

        return {
            "success": False
        }


    short_vn = translate_single_text(
        word
    )


    return {

        "success": True,

        "phonetic": phonetic,

        "short_vn": short_vn,

        "examples": examples
    }


# ============================================================
# 15. DISTRACTORS
# ============================================================

def get_distractors(
    correct_meaning,
    count=3
):

    other_meanings = [

        x["meaning"]

        for x in st.session_state.deck

        if x.get("meaning")
        != correct_meaning
    ]


    pool = list(
        set(
            other_meanings
            + [

                "Sự kiên trì",

                "Khả năng thích ứng",

                "Tác động tích cực",

                "Sự phát triển",

                "Sự hoài nghi",

                "Tạo ra sản phẩm mới",

                "Sự trì hoãn",

                "Sự cân bằng",

                "Lợi ích lâu dài",

                "Sự thay đổi",

                "Kinh nghiệm"

            ]
        )
    )


    if correct_meaning in pool:

        pool.remove(
            correct_meaning
        )


    if len(pool) <= count:

        return pool


    return random.sample(
        pool,
        count
    )


# ============================================================
# 16. ID MỚI
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
# 17. XỬ LÝ ĐÁP ÁN
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


    # --------------------------------------------------------
    # Thời gian trả lời
    # --------------------------------------------------------

    response_time = (
        time.time()
        - st.session_state.review_start_time
    )

    response_time = max(
        0.1,
        response_time
    )


    # --------------------------------------------------------
    # Level cũ
    # --------------------------------------------------------

    old_level = int(
        item.get(
            "level",
            0
        )
    )


    # --------------------------------------------------------
    # Level mới
    # --------------------------------------------------------

    new_level = calculate_level(
        old_level,
        is_correct,
        response_time
    )


    # --------------------------------------------------------
    # Interval mới
    # --------------------------------------------------------

    new_interval = calculate_golden_interval(
        item,
        is_correct,
        response_time
    )


    # --------------------------------------------------------
    # Update thống kê
    # --------------------------------------------------------

    item["level"] = new_level

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


    item["last_response_time"] = round(
        response_time,
        2
    )


    item["last_result"] = (
        "correct"
        if is_correct
        else "wrong"
    )


    # --------------------------------------------------------
    # Thời Điểm Vàng tiếp theo
    # --------------------------------------------------------

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
                f"📈 Cấp độ: "
                f"{old_level} → {new_level}"
            )

        else:

            st.info(
                f"📊 Cấp độ vẫn là "
                f"**Cấp {new_level}**"
            )


        st.info(
            f"🧠 Thời Điểm Vàng được tính lại: "
            f"**{format_interval(new_interval)}**"
        )


        st.caption(
            "Thời gian này được tính dựa trên "
            "cấp độ, tốc độ trả lời và lịch sử "
            "đúng/sai của riêng từ này."
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

        st.warning(
            f"📉 Cấp độ: "
            f"{old_level} → {new_level}"
        )

        st.info(
            f"🔄 Thời Điểm Vàng mới: "
            f"**{format_interval(new_interval)}**"
        )


    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_deck()


    # --------------------------------------------------------
    # Xóa câu hiện tại
    #
    # QUAN TRỌNG:
    # review_started vẫn TRUE
    # để câu tiếp theo tự động xuất hiện.
    # --------------------------------------------------------

    st.session_state.review_item = None

    st.session_state.q_type = None

    st.session_state.q_data = {}


    time.sleep(1.2)

    st.rerun()


# ============================================================
# 18. TẠO CÂU HỎI - 7 DẠNG
# ============================================================

def prepare_review_question(item):

    q_types = [

        # 1. Từ -> chọn nghĩa
        "CHOICE_MEANING",

        # 2. Câu -> điền từ
        "FILL_BLANK",

        # 3. Nghĩa -> gõ từ
        "SPELLING",

        # 4. Ngữ cảnh -> chọn nghĩa
        "CONTEXT_MATCH",

        # 5. Từ + nghĩa -> Đúng / Sai
        "FLASHCARD_TRUE_FALSE",

        # 6. Nghe -> chọn từ
        "AUDIO_CHOICE",

        # 7. Nghĩa -> chọn từ
        "MEANING_CHOICE"

    ]

    chosen_q = random.choice(q_types)

    st.session_state.review_item = item

    st.session_state.q_type = chosen_q

    st.session_state.review_start_time = time.time()

    st.session_state.q_data = {}


    # ========================================================
    # DẠNG 1 + DẠNG 4
    # TỪ -> CHỌN NGHĨA
    # NGỮ CẢNH -> CHỌN NGHĨA
    # ========================================================

    if chosen_q in [

        "CHOICE_MEANING",

        "CONTEXT_MATCH"

    ]:

        options = [

            item["meaning"]

        ]

        options.extend(

            get_distractors(

                item["meaning"],

                3

            )

        )

        random.shuffle(options)

        st.session_state.q_data[
            "options"
        ] = options


    # ========================================================
    # DẠNG 5
    # FLASHCARD ĐÚNG / SAI
    # ========================================================

    elif chosen_q == "FLASHCARD_TRUE_FALSE":

        is_true = random.choice(

            [True, False]

        )

        if is_true:

            meaning = item["meaning"]

        else:

            distractors = get_distractors(

                item["meaning"],

                1

            )

            if distractors:

                meaning = distractors[0]

            else:

                meaning = "Sự phát triển"


        st.session_state.q_data[
            "is_true"
        ] = is_true


        st.session_state.q_data[
            "disp_meaning"
        ] = meaning


    # ========================================================
    # DẠNG 6
    # NGHE -> CHỌN TỪ
    # ========================================================

    elif chosen_q == "AUDIO_CHOICE":

        other_words = [

            x["word"]

            for x in st.session_state.deck

            if x.get("word", "").lower()
            != item["word"].lower()

        ]


        other_words = list(
            set(other_words)
        )


        random.shuffle(
            other_words
        )


        options = [

            item["word"]

        ]


        options.extend(
            other_words[:3]
        )


        # ----------------------------------------------------
        # Nếu sổ tay có ít từ, thêm từ dự phòng
        # ----------------------------------------------------

        fallback_words = [

            "resilience",

            "innovate",

            "experience",

            "development",

            "adaptation",

            "achievement",

            "environment"

        ]


        for word in fallback_words:

            if len(options) >= 4:

                break


            if word.lower() not in [

                x.lower()
                for x in options

            ]:

                options.append(word)


        random.shuffle(
            options
        )


        st.session_state.q_data[
            "options"
        ] = options


    # ========================================================
    # DẠNG 7
    # NGHĨA -> CHỌN TỪ
    # ========================================================

    elif chosen_q == "MEANING_CHOICE":

        other_words = [

            x["word"]

            for x in st.session_state.deck

            if x.get("word", "").lower()
            != item["word"].lower()

        ]


        other_words = list(
            set(other_words)
        )


        random.shuffle(
            other_words
        )


        options = [

            item["word"]

        ]


        options.extend(
            other_words[:3]
        )


        fallback_words = [

            "resilience",

            "innovate",

            "experience",

            "development",

            "adaptation",

            "achievement",

            "environment"

        ]


        for word in fallback_words:

            if len(options) >= 4:

                break


            if word.lower() not in [

                x.lower()
                for x in options

            ]:

                options.append(word)


        random.shuffle(
            options
        )


        st.session_state.q_data[
            "options"
        ] = options

# ============================================================
# 19. HEADER
# ============================================================

st.title(
    "🍌 MochiVocab"
)

st.caption(
    "Thời Điểm Vàng được tính động "
    "theo quá trình ghi nhớ"
)


# ============================================================
# 20. TÍNH TỪ ĐẾN HẠN
# ============================================================

now = datetime.now()

due_count = sum(

    1

    for x in st.session_state.deck

    if x["next_review"] <= now
)


# ============================================================
# 21. MENU
# ============================================================

tab_options = [

    "⏰ Ôn Tập",

    "🔍 Tra Từ Mới",

    "📋 Sổ Tay"

]


tab_labels = {

    "⏰ Ôn Tập":
        f"⏰ Ôn Tập ({due_count})",

    "🔍 Tra Từ Mới":
        "🔍 Tra Từ Mới",

    "📋 Sổ Tay":
        f"📋 Sổ Tay "
        f"({len(st.session_state.deck)})"

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
    # KHÔNG CÓ TỪ CẦN ÔN
    # ========================================================

    elif not due_items:

        # Không còn từ cần ôn
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
                "Cấp độ",
                next_item["level"]
            )


        st.info(
            f"⏰ Còn khoảng "
            f"**{format_remaining(remaining)}**"
        )


        # ----------------------------------------------------
        # COUNTDOWN
        # ----------------------------------------------------

        target_timestamp = int(

            next_item[
                "next_review"
            ].timestamp()
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

        var targetTime =
            {target_timestamp};


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
                Math.floor(
                    diff / 1000
                );


            var days =
                Math.floor(
                    totalSeconds / 86400
                );


            totalSeconds %=
                86400;


            var hours =
                Math.floor(
                    totalSeconds / 3600
                );


            totalSeconds %=
                3600;


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

        # ====================================================
        # MÀN HÌNH CHỜ
        # ====================================================

        if not st.session_state.review_started:

            st.success(
                f"🔥 Có **{len(due_items)} từ** "
                f"đang đến Thời Điểm Vàng."
            )


            st.markdown("---")


            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                Khi bạn bấm **Bắt đầu ôn tập**,
                MochiVocab sẽ chọn từ cần ôn và
                bắt đầu tính thời gian phản hồi.
                """
            )


            if st.button(

                "▶️ BẮT ĐẦU ÔN TẬP",

                type="primary",

                use_container_width=True,

                key="start_review"

            ):

                # --------------------------------------------
                # Ưu tiên từ có level thấp nhất
                # --------------------------------------------

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


        # ====================================================
        # ĐANG ÔN TẬP
        # ====================================================

        else:

            current_item = (
                st.session_state.review_item
            )


            # ------------------------------------------------
            # Nếu chưa có câu hỏi
            # ------------------------------------------------

            if current_item is None:

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
            # NÚT DỪNG ÔN
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
            # LEVEL
            # ------------------------------------------------

            level = item["level"]


            st.progress(
                level / 5
            )


            col1, col2 = st.columns(2)


            with col1:

                st.caption(
                    get_level_name(level)
                )


            with col2:

                st.caption(
                    f"Đã ôn: "
                    f"{item.get('review_count', 0)} lần"
                )


            # ------------------------------------------------
            # THÔNG TIN THỜI GIAN
            # ------------------------------------------------

            current_interval = item.get(
                "interval",
                5
            )


            st.caption(
                f"📐 Khoảng ôn hiện tại: "
                f"**{format_interval(current_interval)}**"
            )


            st.markdown("---")


            # =================================================
            # CÂU HỎI 1
            # =================================================

            if q_type == "CHOICE_MEANING":

                st.markdown(
                    "### 🎲 TRẮC NGHIỆM CHỌN NGHĨA"
                )


                st.info(
                    f"Từ: "
                    f"**{item['word'].upper()}** "
                    f"`{item['phonetic']}`"
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

                    q_data["options"]

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
            # CÂU HỎI 2
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ"
                )


                example = item["example"]


                blanked = re.sub(

                    re.escape(
                        item["word"]
                    ),

                    "________",

                    example,

                    flags=re.IGNORECASE

                )


                if blanked == example:

                    blanked = (

                        example
                        + " ________"

                    )


                st.info(
                    f'"{blanked}"'
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

                    is_correct = (

                        user_ans.strip().lower()

                        == item["word"].lower()

                    )


                    process_answer(

                        is_correct,

                        item["word"].upper()

                    )


            # =================================================
            # CÂU HỎI 3
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

                    key=f"spell_submit_{item['id']}"

                ):

                    is_correct = (

                        user_ans.strip().lower()

                        == item["word"].lower()

                    )


                    process_answer(

                        is_correct,

                        item["word"].upper()

                    )


            # =================================================
            # CÂU HỎI 4
            # =================================================

            elif q_type == "CONTEXT_MATCH":

                st.markdown(
                    "### 🧠 NGHĨA THEO NGỮ CẢNH"
                )


                st.info(
                    f'"{item["example"]}"'
                )


                st.write(

                    f'Từ **{item["word"].upper()}** '

                    "có nghĩa là gì?"

                )


                for index, option in enumerate(

                    q_data["options"]

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
            # CÂU HỎI 5
            # =================================================

            elif q_type == "FLASHCARD_TRUE_FALSE":

                st.markdown(
                    "### ⚡ FLASHCARD PHẢN XẠ"
                )


                st.info(

                    f"Từ: "
                    f"**{item['word'].upper()}**\n\n"

                    f"Nghĩa: "
                    f"**{q_data['disp_meaning'].upper()}**"

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

                    else

                    f"It is important to understand {word_input}."

                )


                st.session_state.temp_word = {

                    "word":
                        word_input,

                    "phonetic":
                        data["phonetic"],

                    "meaning":
                        data["short_vn"],

                    "example":
                        example

                }


    data = (
        st.session_state.temp_word
    )


    if (

        data is not None

        and data["word"]
        == word_input

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

            f"💡 Ví dụ: "

            f"{data['example']}"

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

                    x["word"]
                    == data["word"]

                    for x
                    in st.session_state.deck

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

                        "level":
                            0,

                        "interval":
                            5,

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

                        "⏰ Từ mới sẽ được "
                        "ôn ngay lần đầu."

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


        # ----------------------------------------------------
        # BẢNG
        # ----------------------------------------------------

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

                accuracy = (

                    item.get(
                        "correct_count",
                        0
                    )

                    / accuracy_total

                    * 100

                )


                accuracy_text = (
                    f"{accuracy:.0f}%"
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

                "Trạng thái":
                    get_level_name(
                        item["level"]
                    ),

                "Khoảng ôn":
                    format_interval(
                        item.get(
                            "interval",
                            5
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
        # XÓA
        # ----------------------------------------------------

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
