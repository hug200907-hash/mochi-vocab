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
# 2. CẤU HÌNH HỆ THỐNG MÓC
# ============================================================
#
# Cấp 0:
#   Từ mới -> 0h
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
# Đủ 4 móc -> lên 1 cấp.
#
# Khi sai:
#   - Nếu đang ở móc 1h của cấp 1:
#       giữ nguyên 1h, KHÔNG về cấp 0.
#   - Các móc khác:
#       lùi 1 móc.
#
# ============================================================

LEVEL_HOOKS = {
    0: [0],
    1: [1, 4, 12, 24],
    2: [25, 28, 36, 48],
    3: [49, 52, 60, 72],
    4: [73, 76, 84, 96],
    5: [97, 100, 108, 120],
}

MAX_LEVEL = 5


# ============================================================
# 3. SESSION STATE
# ============================================================

defaults = {
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

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 4. FORMAT THỜI GIAN
# ============================================================

def format_interval(hours):
    hours = float(max(0, hours))

    if hours < 1:
        minutes = round(hours * 60)
        return f"{minutes} phút"

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
# 5. HỆ THỐNG MÓC
# ============================================================

def get_level_hooks(level):
    return LEVEL_HOOKS.get(level, LEVEL_HOOKS[0])


def get_hook_index(item):
    """
    Trả về vị trí móc hiện tại.

    Ví dụ:
    Cấp 1:
        hook_index = 0 -> 1h
        hook_index = 1 -> 4h
        hook_index = 2 -> 12h
        hook_index = 3 -> 24h
    """

    level = int(item.get("level", 0))

    if level <= 0:
        return 0

    hooks = get_level_hooks(level)

    hook_index = int(item.get("hook_index", 0))

    return max(0, min(hook_index, len(hooks) - 1))


def get_current_hook_hours(item):
    level = int(item.get("level", 0))

    if level <= 0:
        return 0

    hooks = get_level_hooks(level)
    hook_index = get_hook_index(item)

    return hooks[hook_index]


def get_current_level_name(level):
    names = {
        0: "🆕 Cấp 0 - Từ mới",
        1: "🥉 Cấp 1",
        2: "🥈 Cấp 2",
        3: "🥇 Cấp 3",
        4: "💎 Cấp 4",
        5: "🏆 Cấp 5 - Ghi nhớ rất tốt",
    }

    return names.get(level, "Cấp 0")


def get_progress_text(item):
    level = int(item.get("level", 0))

    if level == 0:
        return "0/4 móc • Từ mới"

    hook_index = get_hook_index(item)
    return f"{hook_index + 1}/4 móc"


def get_hook_description(item):
    level = int(item.get("level", 0))

    if level == 0:
        return "🆕 Từ mới • 0h"

    hooks = get_level_hooks(level)
    hook_index = get_hook_index(item)

    parts = []

    for i, hook in enumerate(hooks):
        if i < hook_index:
            parts.append(f"✅ {hook}h")
        elif i == hook_index:
            parts.append(f"🔥 {hook}h")
        else:
            parts.append(f"○ {hook}h")

    return " → ".join(parts)


# ============================================================
# 6. XỬ LÝ ĐÚNG
# ============================================================

def advance_hook(item):
    """
    Trả về:
        new_level,
        new_hook_index
    """

    old_level = int(item.get("level", 0))

    # TỪ MỚI:
    # trả lời đúng lần đầu -> Cấp 1, móc 1h
    if old_level == 0:
        return 1, 0

    old_hook = get_hook_index(item)
    hooks = get_level_hooks(old_level)

    # Chưa đến móc cuối -> đi móc tiếp theo
    if old_hook < len(hooks) - 1:
        return old_level, old_hook + 1

    # Đã đủ 4 móc
    # -> lên cấp tiếp theo
    if old_level < MAX_LEVEL:
        return old_level + 1, 0

    # Cấp 5 đã max
    # Giữ tại móc cuối
    return old_level, old_hook


# ============================================================
# 7. XỬ LÝ SAI
# ============================================================

def decrease_hook(item):
    """
    Sai 1 lần -> lùi 1 móc.

    Đặc biệt:
    Cấp 1 móc 1h -> vẫn giữ Cấp 1 móc 1h.
    KHÔNG bao giờ về Cấp 0 do trả lời sai.
    """

    old_level = int(item.get("level", 0))

    # Cấp 0 thì vẫn cấp 0
    if old_level <= 0:
        return 0, 0

    old_hook = get_hook_index(item)

    # ========================================================
    # ĐẶC BIỆT:
    # Cấp 1 + móc đầu tiên = 1h
    # Sai -> vẫn giữ 1h
    # ========================================================

    if old_level == 1 and old_hook == 0:
        return 1, 0

    # Nếu không phải móc đầu
    if old_hook > 0:
        return old_level, old_hook - 1

    # Đang ở móc đầu của cấp > 1
    # -> lùi về móc cuối của cấp trước
    if old_level > 1:
        previous_level = old_level - 1
        previous_hooks = get_level_hooks(previous_level)

        return previous_level, len(previous_hooks) - 1

    return 1, 0


# ============================================================
# 8. ĐẶT THỜI GIAN ÔN TIẾP
# ============================================================

def schedule_next_review(item):
    hours = get_current_hook_hours(item)

    # Cấp 0 = từ mới, ôn ngay
    if hours <= 0:
        item["next_review"] = datetime.now()
    else:
        item["next_review"] = (
            datetime.now() + timedelta(hours=hours)
        )


# ============================================================
# 9. KIỂM TRA TỪ QUÁ HẠN
# ============================================================

def handle_overdue_item(item):
    """
    Nếu người dùng không làm đúng móc trong thời gian quy định,
    từ sẽ bị hạ 1 móc.

    Không hạ Cấp 1 móc 1h xuống Cấp 0.
    """

    if item.get("overdue_handled", False):
        return False

    next_review = item.get("next_review")

    if not isinstance(next_review, datetime):
        return False

    if next_review > datetime.now():
        return False

    # Nếu chưa từng ôn thì đây chỉ là từ mới
    # Không tự động hạ gì cả.
    if int(item.get("review_count", 0)) == 0:
        return False

    old_level = int(item.get("level", 0))
    old_hook = get_hook_index(item)

    new_level, new_hook = decrease_hook(item)

    # Nếu đã ở Cấp 1 - móc 1h thì không thay đổi
    if (
        old_level == 1
        and old_hook == 0
        and new_level == 1
        and new_hook == 0
    ):
        item["overdue_handled"] = True
        schedule_next_review(item)
        return True

    item["level"] = new_level
    item["hook_index"] = new_hook
    item["overdue_handled"] = True
    item["last_result"] = "overdue"

    schedule_next_review(item)

    return True


def process_all_overdue():
    changed = False

    for item in st.session_state.deck:
        if handle_overdue_item(item):
            changed = True

    if changed:
        save_deck()


# ============================================================
# 10. LOAD DATA
# ============================================================

if not st.session_state.data_loaded:

    saved_data = local_storage.getItem("mochi_deck_data")

    if saved_data:
        try:
            items = json.loads(saved_data)

            cleaned_items = []

            for item in items:

                # --------------------------------------------
                # next_review
                # --------------------------------------------

                if "next_review" not in item:
                    item["next_review"] = datetime.now().isoformat()

                if isinstance(item["next_review"], str):
                    try:
                        item["next_review"] = datetime.fromisoformat(
                            item["next_review"]
                        )
                    except Exception:
                        item["next_review"] = datetime.now()

                # --------------------------------------------
                # level
                # --------------------------------------------

                item["level"] = max(
                    0,
                    min(
                        int(item.get("level", 0)),
                        MAX_LEVEL
                    )
                )

                # --------------------------------------------
                # hook_index
                # --------------------------------------------

                if item["level"] == 0:
                    item["hook_index"] = 0
                else:
                    max_hook = len(
                        get_level_hooks(item["level"])
                    ) - 1

                    item["hook_index"] = max(
                        0,
                        min(
                            int(item.get("hook_index", 0)),
                            max_hook
                        )
                    )

                # --------------------------------------------
                # thống kê
                # --------------------------------------------

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

                item["overdue_handled"] = item.get(
                    "overdue_handled",
                    False
                )

                cleaned_items.append(item)

            st.session_state.deck = cleaned_items

        except Exception:
            st.session_state.deck = []

    st.session_state.data_loaded = True


# ============================================================
# 11. SAVE DATA
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
# 12. GOOGLE TRANSLATE
# ============================================================

def translate_single_text(text):

    if not text or not text.strip():
        return text

    try:

        url = (
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx"
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
            timeout=5
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

            if isinstance(data, list) and data:

                result = []

                for item in data[0]:

                    if (
                        isinstance(item, list)
                        and len(item) > 0
                        and item[0]
                    ):
                        result.append(item[0])

                translated = "".join(result).strip()

                if translated:
                    return translated

    except Exception:
        pass

    return text


# ============================================================
# 13. TRA TỪ
# ============================================================

def fetch_word_full_data_FAST(word):

    url = (
        "https://api.dictionaryapi.dev/api/v2/entries/en/"
        f"{urllib.parse.quote(word)}"
    )

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

                # --------------------------------------------
                # PHONETIC
                # --------------------------------------------

                phonetic = (
                    first.get("phonetic")
                    or phonetic
                )

                if phonetic == f"/{word}/":

                    for p in first.get(
                        "phonetics",
                        []
                    ):

                        if p.get("text"):
                            phonetic = p["text"]
                            break

                # --------------------------------------------
                # EXAMPLE
                # --------------------------------------------

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

    except Exception:
        pass

    # --------------------------------------------
    # DỊCH CHÍNH TỪ
    # --------------------------------------------

    vietnamese = translate_single_text(word)

    # Nếu không dịch được
    if (
        not vietnamese
        or vietnamese.strip().lower()
        == word.strip().lower()
    ):
        vietnamese = f"Chưa có bản dịch cho {word}"

    if not examples:
        examples.append(
            f"It is important to understand {word}."
        )

    return {
        "success": True,
        "phonetic": phonetic,
        "short_vn": vietnamese,
        "examples": examples,
    }


# ============================================================
# 14. TRA CÂU VÍ DỤ ONLINE
# ============================================================

def fetch_online_word_data(word):

    try:

        url = (
            "https://api.dictionaryapi.dev/api/v2/entries/en/"
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
            timeout=4
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

                        if definition.get("example"):
                            return definition["example"]

    except Exception:
        pass

    return None


# ============================================================
# 15. AUDIO
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
        new SpeechSynthesisUtterance('{safe_word}');

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
# 16. ID
# ============================================================

def get_next_id():

    if not st.session_state.deck:
        return 1

    return max(
        int(x.get("id", 0))
        for x in st.session_state.deck
    ) + 1


# ============================================================
# 17. TẠO CÂU HỎI
# ============================================================

def prepare_review_question(item):

    # Không còn AUDIO_CHOICE
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

    # --------------------------------------------
    # Lấy câu ví dụ
    # --------------------------------------------

    if not example:

        online_example = fetch_online_word_data(
            word
        )

        if online_example:
            example = online_example
            item["example"] = online_example

        else:
            example = (
                f"The word '{word}' "
                "is very important."
            )

    # --------------------------------------------
    # Các từ khác trong deck
    # --------------------------------------------

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
            "answer": meaning,
        }

    # ========================================================
    # 2. ĐIỀN TỪ VÀO CHỖ TRỐNG
    # ========================================================

    elif chosen_q == "FILL_BLANK":

        # Tìm đúng từ trong câu.
        blank_sentence = re.sub(
            rf"\b{re.escape(word)}\b",
            "_____",
            example,
            flags=re.IGNORECASE
        )

        # Nếu ví dụ không chứa từ,
        # tạo câu có chứa từ.
        if blank_sentence == example:

            blank_sentence = (
                f"_____ ({meaning})"
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
            "context": example,
            "word": word,
            "options": options,
            "answer": meaning,
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

    old_hook = get_hook_index(item)

    # ========================================================
    # ĐÚNG
    # ========================================================

    if is_correct:

        new_level, new_hook = advance_hook(
            item
        )

        item["level"] = new_level
        item["hook_index"] = new_hook

        item["correct_count"] = int(
            item.get("correct_count", 0)
        ) + 1

        item["review_count"] = int(
            item.get("review_count", 0)
        ) + 1

        item["last_response_time"] = round(
            response_time,
            2
        )

        item["last_result"] = "correct"

        item["overdue_handled"] = False

        schedule_next_review(item)

        st.success("✨ Chính xác!")

        st.write(
            f"⚡ Thời gian phản hồi: "
            f"**{response_time:.1f} giây**"
        )

        if new_level > old_level:

            st.success(
                f"📈 Lên cấp: "
                f"Cấp {old_level} → "
                f"Cấp {new_level}"
            )

        elif new_hook > old_hook:

            st.success(
                f"📈 Tiến lên móc "
                f"{new_hook + 1}/4"
            )

        else:

            st.info(
                f"📊 Đang ở "
                f"Cấp {new_level}"
            )

        st.info(
            f"🧠 Móc tiếp theo: "
            f"**{format_interval(get_current_hook_hours(item))}**"
        )

        if new_level == 5 and new_hook == 3:

            st.balloons()

            st.success(
                "🏆 Từ này đã hoàn thành "
                "Cấp 5!"
            )

    # ========================================================
    # SAI
    # ========================================================

    else:

        new_level, new_hook = decrease_hook(
            item
        )

        item["level"] = new_level
        item["hook_index"] = new_hook

        item["wrong_count"] = int(
            item.get("wrong_count", 0)
        ) + 1

        item["review_count"] = int(
            item.get("review_count", 0)
        ) + 1

        item["last_response_time"] = round(
            response_time,
            2
        )

        item["last_result"] = "wrong"

        item["overdue_handled"] = False

        schedule_next_review(item)

        st.error("❌ Chưa chính xác.")

        st.warning(
            f"Đáp án đúng: "
            f"**{correct_ans_text}**"
        )

        # Cấp 1 - móc 1h
        if (
            old_level == 1
            and old_hook == 0
        ):

            st.warning(
                "🔒 Đây là móc 1h của Cấp 1, "
                "sai vẫn giữ nguyên móc 1h."
            )

        else:

            st.warning(
                f"📉 Lùi từ "
                f"Cấp {old_level}, móc "
                f"{old_hook + 1}/4 "
                f"→ Cấp {new_level}, móc "
                f"{new_hook + 1}/4"
            )

        st.info(
            f"🔄 Móc mới: "
            f"**{format_interval(get_current_hook_hours(item))}**"
        )

    save_deck()

    # Reset câu hỏi hiện tại
    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}

    time.sleep(0.8)

    st.rerun()


# ============================================================
# 19. RESET TẤT CẢ VỀ CẤP 0
# ============================================================

def reset_all_to_level_zero():

    for item in st.session_state.deck:

        item["level"] = 0
        item["hook_index"] = 0

        item["next_review"] = datetime.now()

        item["review_count"] = 0
        item["correct_count"] = 0
        item["wrong_count"] = 0

        item["last_response_time"] = None
        item["last_result"] = None
        item["overdue_handled"] = False

    st.session_state.review_item = None
    st.session_state.review_started = False
    st.session_state.q_type = None
    st.session_state.q_data = {}

    save_deck()


# ============================================================
# 20. XỬ LÝ QUÁ HẠN
# ============================================================

process_all_overdue()


# ============================================================
# 21. HEADER
# ============================================================

st.title("🍌 MochiVocab")

st.caption(
    "Dynamic Golden Time • Hệ thống 4 móc mỗi cấp"
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
    "📋 Sổ Tay",
]

tab_labels = {
    "⏰ Ôn Tập": f"⏰ Ôn Tập ({due_count})",
    "🔍 Tra Từ Mới": "🔍 Tra Từ Mới",
    "📋 Sổ Tay":
        f"📋 Sổ Tay ({len(st.session_state.deck)})",
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
    # KHÔNG CÓ TỪ
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

        # Countdown
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

    # --------------------------------------------------------
    # CÓ TỪ CẦN ÔN
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

MochiVocab sẽ ưu tiên những từ có cấp thấp
để củng cố trí nhớ trước.
"""
            )

            if st.button(
                "▶️ BẮT ĐẦU ÔN TẬP",
                type="primary",
                use_container_width=True,
                key="start_review",
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

            item = st.session_state.review_item

            q_type = st.session_state.q_type
            q_data = st.session_state.q_data

            # ------------------------------------------------
            # DỪNG
            # ------------------------------------------------

            if st.button(
                "⏹️ Dừng ôn tập",
                key="stop_review",
            ):

                st.session_state.review_started = False
                st.session_state.review_item = None
                st.session_state.q_type = None
                st.session_state.q_data = {}
                st.session_state.review_start_time = 0

                st.rerun()

            # ------------------------------------------------
            # THÔNG TIN TỪ
            # ------------------------------------------------

            level = int(
                item.get("level", 0)
            )

            hook_index = get_hook_index(
                item
            )

            st.progress(
                level / MAX_LEVEL
            )

            col1, col2 = st.columns(2)

            with col1:

                st.caption(
                    get_current_level_name(
                        level
                    )
                )

            with col2:

                st.caption(
                    f"Móc: "
                    f"{hook_index + 1}/4"
                    if level > 0
                    else "Từ mới"
                )

            st.info(
                f"🧠 "
                f"{get_hook_description(item)}"
            )

            st.caption(
                f"⏰ Móc hiện tại: "
                f"**{format_interval(get_current_hook_hours(item))}**"
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
                    key="choice_audio",
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
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"],
                        )

            # =================================================
            # DẠNG 2
            # =================================================

            elif q_type == "FILL_BLANK":

                st.markdown(
                    "### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG"
                )

                st.info(
                    f'"{q_data.get("sentence")}"'
                )

                user_ans = st.text_input(
                    "Từ còn thiếu:",
                    key=f"fill_{item['id']}",
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=f"fill_submit_{item['id']}",
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].strip().lower(),
                        item["word"].upper(),
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
                    key=f"spell_{item['id']}",
                )

                if st.button(
                    "Xác Nhận",
                    type="primary",
                    key=f"spell_submit_{item['id']}",
                ):

                    process_answer(
                        user_ans.strip().lower()
                        == item["word"].strip().lower(),
                        item["word"].upper(),
                    )

            # =================================================
            # DẠNG 4
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
                    ):

                        process_answer(
                            option
                            == item["meaning"],
                            item["meaning"],
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
                        key=f"true_{item['id']}",
                    ):

                        process_answer(
                            q_data["is_true"],
                            "ĐÚNG"
                            if q_data["is_true"]
                            else "SAI",
                        )

                with col2:

                    if st.button(
                        "❌ SAI",
                        key=f"false_{item['id']}",
                    ):

                        process_answer(
                            not q_data["is_true"],
                            "SAI"
                            if not q_data["is_true"]
                            else "ĐÚNG",
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
                    ):

                        process_answer(
                            option.lower()
                            == item["word"].lower(),
                            item["word"].upper(),
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
        ),
    ).strip().lower()

    if st.button(
        "🔎 Tra Từ",
        type="primary",
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
                        f"to understand {word_input}."
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
            f"{data['meaning'].upper()}"
        )

        st.caption(
            f"💡 Ví dụ: {data['example']}"
        )

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "🔊 Nghe",
                key="new_word_audio",
            ):

                play_audio_script(
                    data["word"]
                )

        with col2:

            if st.button(
                "➕ Thêm vào Sổ Tay",
                key="add_new_word",
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

                    # ----------------------------------------
                    # TỪ MỚI = CẤP 0 / 0h
                    # ----------------------------------------

                    new_item = {

                        "id": get_next_id(),

                        "word": data["word"],

                        "phonetic":
                            data["phonetic"],

                        "meaning":
                            data["meaning"],

                        "example":
                            data["example"],

                        "level": 0,

                        "hook_index": 0,

                        "review_count": 0,

                        "correct_count": 0,

                        "wrong_count": 0,

                        "last_response_time":
                            None,

                        "last_result":
                            None,

                        "overdue_handled":
                            False,

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
                        "⏰ Từ mới bắt đầu ở "
                        "**Cấp 0 - 0h**."
                    )

                    time.sleep(0.7)

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
                item.get("correct_count", 0)
                + item.get("wrong_count", 0)
            )

            # =================================================
            # FIX LỖI accuracy_text
            # =================================================

            if accuracy_total > 0:

                accuracy_text = (
                    f"{item.get('correct_count', 0)} "
                    "/ accuracy_total * 100:.0f}%"
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
                    (
                        f"{get_hook_index(item) + 1}/4"
                        if item["level"] > 0
                        else "0/4"
                    ),

                "Trạng thái":
                    get_level_name(
                        item["level"]
                    ),

                "Móc hiện tại":
                    format_interval(
                        get_current_hook_hours(item)
                    ),

                "Tiến độ":
                    get_progress_text(item),

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
            hide_index=True,
        )

        st.markdown("---")

        # ====================================================
        # RESET CẤP 0
        # ====================================================

        st.warning(
            "⚠️ Reset tất cả sẽ đưa toàn bộ từ "
            "về **Cấp 0 - 0h** và xóa tiến độ ôn tập."
        )

        if st.button(
            "🔄 RESET TẤT CẢ VỀ CẤP 0",
            type="secondary",
            use_container_width=True,
        ):

            reset_all_to_level_zero()

            st.success(
                "✅ Đã reset toàn bộ từ "
                "về Cấp 0 - 0h."
            )

            time.sleep(0.5)

            st.rerun()

        st.markdown("---")

        # ====================================================
        # DELETE ALL
        # ====================================================

        if st.button(
            "🗑️ XÓA TOÀN BỘ TỪ VỰNG",
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
# 25. FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "🍌 MochiVocab • Dynamic Golden Time"
)
