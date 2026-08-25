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
# 2. HỆ THỐNG CẤP + MÓC & THUẬT TOÁN TẠO GỢI Ý (MỚI)
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


def generate_hint_pattern(word, level, hook):
    """
    Sinh chuỗi gợi ý ký tự (vd: "d _ s _ u _ s") dựa trên độ dài từ và cấp/móc.
    - Từ ngắn (<=5 ký tự): tối đa 3 chữ.
    - Từ dài (>5 ký tự): tối đa 5 chữ.
    - Móc càng thấp -> hiện càng nhiều chữ.
    - Các chữ gợi ý không đứng sát nhau.
    """
    if not word:
        return ""

    word_clean = word.strip()
    length = len(word_clean)

    # 1. Chuẩn hóa tiến trình học (Móc 0/20 đến Móc 20/20)
    total_progress_steps = MAX_LEVEL * HOOKS_PER_LEVEL  # 20 bước
    if level <= 0:
        current_step = 0
    else:
        current_step = (level - 1) * HOOKS_PER_LEVEL + hook

    # Tính tỷ lệ thành thục (0.0 đến 1.0)
    progress_ratio = current_step / float(total_progress_steps)

    # 2. Xác định số lượng chữ cái gợi ý tối đa
    max_hints_allowed = 3 if length <= 5 else 5
    max_hints_allowed = min(max_hints_allowed, length)

    # Tỷ lệ nghịch: Móc càng thấp -> Gợi ý càng nhiều
    hint_count = int(round((1.0 - progress_ratio) * max_hints_allowed))

    # Nếu chưa thuộc hoàn toàn (chưa đạt Cấp 5 Móc 4), giữ ít nhất 1 gợi ý
    if hint_count == 0 and current_step < total_progress_steps:
        hint_count = 1

    if hint_count <= 0:
        return " ".join(["_"] * length)

    # 3. Chọn các vị trí ký tự không đứng sát nhau
    selected_indices = [0]  # Ưu tiên chữ đầu tiên làm điểm tựa

    candidate_indices = [i for i in range(2, length)]

    while len(selected_indices) < hint_count and candidate_indices:
        chosen = random.choice(candidate_indices)
        selected_indices.append(chosen)
        # Loại bỏ vị trí vừa chọn và 2 vị trí kề sát
        candidate_indices = [
            idx for idx in candidate_indices 
            if abs(idx - chosen) > 1
        ]

    # Nếu không còn chỗ giãn cách nhưng vẫn thiếu slot, điền vị trí còn trống
    if len(selected_indices) < hint_count:
        for i in range(length):
            if i not in selected_indices and len(selected_indices) < hint_count:
                selected_indices.append(i)

    selected_indices.sort()

    # 4. Ráp thành chuỗi hiển thị
    display_chars = []
    for i, char in enumerate(word_clean):
        if i in selected_indices:
            display_chars.append(char.lower())
        else:
            display_chars.append("_")

    return " ".join(display_chars)


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
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days} ngày {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# ============================================================
# 5. THÔNG TIN CẤP / MÓC
# ============================================================

def get_level_name(level):
    names = {
        0: "🆕 Cấp 0 — Từ mới",
        1: "🥉 Cấp 1 — Đang hình thành",
        2: "🥈 Cấp 2 — Đã nhớ",
        3: "🥇 Cấp 3 — Nhớ khá tốt",
        4: "💎 Cấp 4 — Nhớ lâu",
        5: "🏆 Cấp 5 — Ghi nhớ rất tốt",
    }
    return names.get(level, "🆕 Cấp 0 — Từ mới")


def get_level_hooks(level):
    return LEVEL_HOOKS.get(level, [])


def get_hook_hours(item):
    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

    if level <= 0:
        return 0

    hooks = get_level_hooks(level)
    if not hooks:
        return 0

    hook = max(1, min(hook, len(hooks)))
    return hooks[hook - 1]


def get_current_interval(item):
    return get_hook_hours(item)


def get_progress_text(item):
    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

    if level == 0:
        return "Cấp 0 • Từ mới"
    return f"Cấp {level} • Móc {hook}/4"


# ============================================================
# 6. CHUẨN HÓA ITEM CŨ
# ============================================================

def normalize_item(item):
    item = dict(item)

    try:
        item["id"] = int(item.get("id", 0))
    except Exception:
        item["id"] = 0

    item["word"] = str(item.get("word", "")).strip()
    item["phonetic"] = str(item.get("phonetic", "")).strip()
    item["meaning"] = str(item.get("meaning", "")).strip()
    item["example"] = str(item.get("example", "")).strip()

    try:
        level = int(item.get("level", 0))
    except Exception:
        level = 0

    level = max(0, min(MAX_LEVEL, level))
    has_hook = "hook" in item

    try:
        hook = int(item.get("hook", 0))
    except Exception:
        hook = 0

    if not has_hook and level > 0:
        try:
            old_interval = float(item.get("interval", 1))
        except Exception:
            old_interval = 1

        best_level = 1
        best_hook = 1
        best_distance = float("inf")

        for lv, hooks in LEVEL_HOOKS.items():
            for hk, hours in enumerate(hooks, start=1):
                distance = abs(hours - old_interval)
                if distance < best_distance:
                    best_distance = distance
                    best_level = lv
                    best_hook = hk

        level = best_level
        hook = best_hook

    if level == 0:
        hook = 0
    else:
        hook = max(1, min(HOOKS_PER_LEVEL, hook))

    item["level"] = level
    item["hook"] = hook

    try:
        item["review_count"] = int(item.get("review_count", 0))
    except Exception:
        item["review_count"] = 0

    try:
        item["correct_count"] = int(item.get("correct_count", 0))
    except Exception:
        item["correct_count"] = 0

    try:
        item["wrong_count"] = int(item.get("wrong_count", 0))
    except Exception:
        item["wrong_count"] = 0

    item["last_response_time"] = item.get("last_response_time", None)
    item["last_result"] = item.get("last_result", None)

    next_review = item.get("next_review")

    if isinstance(next_review, datetime):
        item["next_review"] = next_review
    elif isinstance(next_review, str):
        try:
            item["next_review"] = datetime.fromisoformat(next_review)
        except Exception:
            item["next_review"] = datetime.now()
    else:
        item["next_review"] = datetime.now()

    item["interval"] = get_current_interval(item)
    item.setdefault("_overdue_processed", False)

    return item


# ============================================================
# 7. LOAD LOCAL STORAGE
# ============================================================

if not st.session_state.data_loaded:
    saved_data = None
    try:
        saved_data = local_storage.getItem("mochi_deck_data")
    except Exception:
        saved_data = None

    if saved_data:
        try:
            items = json.loads(saved_data)
            if isinstance(items, list):
                cleaned_items = []
                for raw_item in items:
                    if isinstance(raw_item, dict):
                        cleaned_items.append(normalize_item(raw_item))
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
        copy_item = dict(item)
        if isinstance(copy_item.get("next_review"), datetime):
            copy_item["next_review"] = copy_item["next_review"].isoformat()
        serializable_deck.append(copy_item)

    try:
        local_storage.setItem(
            "mochi_deck_data",
            json.dumps(serializable_deck, ensure_ascii=False)
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
            ids.append(int(item.get("id", 0)))
        except Exception:
            pass

    if not ids:
        return 1

    return max(ids) + 1


# ============================================================
# 10. GOOGLE TRANSLATE
# ============================================================

def translate_google(text):
    if not text:
        return ""
    text = str(text).strip()
    if not text:
        return ""

    try:
        encoded_text = urllib.parse.quote(text)
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
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36",
                "Accept": "application/json,text/plain,*/*"
            }
        )

        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8")

        data = json.loads(raw)
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
            result_parts = []
            for part in data[0]:
                if isinstance(part, list) and len(part) > 0 and part[0]:
                    result_parts.append(str(part[0]))

            result = "".join(result_parts).strip()
            if result:
                return result
    except Exception:
        pass

    return ""


# ============================================================
# 11. MYMEMORY DỰ PHÒNG
# ============================================================

def translate_mymemory(text):
    if not text:
        return ""
    text = str(text).strip()
    if not text:
        return ""

    try:
        params = urllib.parse.urlencode({"q": text, "langpair": "en|vi"})
        url = f"https://api.mymemory.translated.net/get?{params}"

        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8")

        data = json.loads(raw)
        response_data = data.get("responseData", {})
        translated = response_data.get("translatedText", "")

        if translated:
            translated = str(translated).strip()
            if translated.lower() != text.lower():
                return translated
    except Exception:
        pass

    return ""


# ============================================================
# 12. HÀM DỊCH CHÍNH
# ============================================================

def translate_single_text(text):
    if not text:
        return ""
    text = str(text).strip()
    if not text:
        return ""

    result = translate_google(text)
    if result:
        return result

    result = translate_mymemory(text)
    if result:
        return result

    return ""


# ============================================================
# 13. DICTIONARY API
# ============================================================

def fetch_dictionary_data(word):
    if not word:
        return None

    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list) and data:
                return data
    except Exception:
        pass

    return None


# ============================================================
# 14. LẤY FULL DATA CỦA TỪ
# ============================================================

def fetch_word_full_data(word):
    data = fetch_dictionary_data(word)
    if not data:
        return {"success": False, "error": "Không tìm thấy từ trên Dictionary API."}

    first = data[0]
    phonetic = first.get("phonetic", "") or ""

    if not phonetic:
        for phonetic_obj in first.get("phonetics", []):
            if phonetic_obj.get("text"):
                phonetic = phonetic_obj["text"]
                break

    meanings = []
    examples = []

    for meaning_obj in first.get("meanings", []):
        part_of_speech = meaning_obj.get("partOfSpeech", "")
        for definition_obj in meaning_obj.get("definitions", []):
            definition = definition_obj.get("definition", "")
            example = definition_obj.get("example", "")

            if definition:
                meanings.append({"type": part_of_speech, "definition": definition})

            if example:
                examples.append(example)

    short_vn = translate_single_text(word)

    if not short_vn and meanings:
        first_definition = meanings[0].get("definition", "")
        if first_definition:
            short_vn = translate_single_text(first_definition)

    if not short_vn:
        short_vn = ""

    return {
        "success": True,
        "phonetic": phonetic,
        "short_vn": short_vn,
        "meanings": meanings,
        "examples": examples,
    }


# ============================================================
# 15. LẤY CÂU VÍ DỤ ONLINE
# ============================================================

def fetch_online_example(word):
    data = fetch_dictionary_data(word)
    if not data:
        return None

    for meaning_obj in data[0].get("meanings", []):
        for definition_obj in meaning_obj.get("definitions", []):
            example = definition_obj.get("example")
            if example:
                return example

    return None


# ============================================================
# 16. PHÁT ÂM
# ============================================================

def play_audio_script(word):
    safe_word = (
        word.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
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

    st.components.v1.html(js_code, height=0)


# ============================================================
# 17. TẠO CÂU HỎI
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

    chosen_q = random.choice(q_types)

    st.session_state.review_item = item
    st.session_state.q_type = chosen_q
    st.session_state.review_start_time = time.time()
    st.session_state.q_data = {}

    word = item.get("word", "").strip()
    meaning = item.get("meaning", "").strip()
    example = item.get("example", "").strip()

    if not example:
        online_example = fetch_online_example(word)
        if online_example:
            example = online_example
        else:
            example = f"It is important to understand {word}."

    deck_words = [
        x.get("word", "").strip()
        for x in st.session_state.deck
        if x.get("word", "").strip() and x.get("word", "").strip().lower() != word.lower()
    ]

    deck_meanings = [
        x.get("meaning", "").strip()
        for x in st.session_state.deck
        if x.get("meaning", "").strip() and x.get("meaning", "").strip().lower() != meaning.lower()
    ]

    # 1. TỪ -> CHỌN NGHĨA
    if chosen_q == "CHOICE_MEANING":
        options = [meaning]
        if deck_meanings:
            distractors = random.sample(deck_meanings, min(len(deck_meanings), 3))
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
            "question": word,
            "options": options,
            "answer": meaning,
        }

    # 2. ĐIỀN TỪ (CÓ GỢI Ý KÝ TỰ DỰA TRÊN MÓC)
    elif chosen_q == "FILL_BLANK":
        blank_sentence = re.sub(
            r"\b" + re.escape(word) + r"\b",
            "_____",
            example,
            flags=re.IGNORECASE
        )

        if blank_sentence == example:
            blank_sentence = f"{example} _____"

        # Sinh gợi ý chữ cái theo Móc
        hint_pattern = generate_hint_pattern(
            word,
            item.get("level", 0),
            item.get("hook", 0)
        )

        st.session_state.q_data = {
            "sentence": blank_sentence,
            "answer": word,
            "word": word,
            "hint_pattern": hint_pattern,
        }

    # 3. NGHĨA -> GÕ TỪ
    elif chosen_q == "SPELLING":
        st.session_state.q_data = {
            "question": meaning,
            "answer": word,
        }

    # 4. CONTEXT
    elif chosen_q == "CONTEXT_MATCH":
        options = [meaning]
        if deck_meanings:
            distractors = random.sample(deck_meanings, min(len(deck_meanings), 3))
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
            "answer": meaning,
        }

    # 5. ĐÚNG / SAI
    elif chosen_q == "FLASHCARD_TRUE_FALSE":
        is_true = random.choice([True, False])
        if is_true or not deck_meanings:
            display_meaning = meaning
            answer = True
        else:
            display_meaning = random.choice(deck_meanings)
            answer = False

        st.session_state.q_data = {
            "word": word,
            "disp_meaning": display_meaning,
            "is_true": answer,
            "answer": answer,
        }

    # 6. NGHĨA -> CHỌN TỪ
    elif chosen_q == "MEANING_CHOICE":
        options = [word]
        if deck_words:
            sampled_words = random.sample(deck_words, min(len(deck_words), 3))
            for w in sampled_words:
                if w.lower() not in [x.lower() for x in options]:
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
            if fb.lower() not in [x.lower() for x in options]:
                options.append(fb)

        random.shuffle(options)
        st.session_state.q_data = {
            "word": word,
            "question": meaning,
            "options": options,
            "answer": word,
        }


# ============================================================
# 18. XỬ LÝ QUÁ HẠN
# ============================================================

def apply_overdue_penalty(item):
    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

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
    item["interval"] = get_current_interval(item)
    item["next_review"] = datetime.now()

    return changed


def process_overdue_items():
    now = datetime.now()
    changed = False

    for item in st.session_state.deck:
        if item.get("level", 0) <= 0:
            continue

        next_review = item.get("next_review")
        if not isinstance(next_review, datetime):
            continue

        if next_review <= now:
            if not item.get("_overdue_processed", False):
                changed_now = apply_overdue_penalty(item)
                item["_overdue_processed"] = True
                if changed_now:
                    changed = True

    if changed:
        save_deck()


# ============================================================
# 19. TIẾN MÓC
# ============================================================

def advance_after_correct(item):
    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

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
    item["interval"] = get_current_interval(item)


# ============================================================
# 20. LÙI MÓC
# ============================================================

def move_back_after_wrong(item):
    level = int(item.get("level", 0))
    hook = int(item.get("hook", 0))

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
    item["interval"] = get_current_interval(item)


# ============================================================
# 21. XỬ LÝ ĐÁP ÁN
# ============================================================

def process_answer(is_correct, correct_ans_text):
    item = st.session_state.review_item
    if item is None:
        return

    response_time = max(0.1, time.time() - st.session_state.review_start_time)
    old_level = int(item.get("level", 0))
    old_hook = int(item.get("hook", 0))

    if is_correct:
        item["review_count"] = int(item.get("review_count", 0)) + 1
        item["correct_count"] = int(item.get("correct_count", 0)) + 1
        item["last_result"] = "correct"
        advance_after_correct(item)
    else:
        item["review_count"] = int(item.get("review_count", 0)) + 1
        item["wrong_count"] = int(item.get("wrong_count", 0)) + 1
        item["last_result"] = "wrong"
        move_back_after_wrong(item)

    item["last_response_time"] = round(response_time, 2)
    new_interval_hours = get_current_interval(item)

    if new_interval_hours <= 0:
        item["next_review"] = datetime.now()
    else:
        item["next_review"] = datetime.now() + timedelta(hours=new_interval_hours)

    item["_overdue_processed"] = False
    item["interval"] = new_interval_hours

    if is_correct:
        st.success("✨ Chính xác!")
        st.write(f"⚡ Thời gian phản hồi: **{response_time:.1f} giây**")
        st.success(
            f"📈 Cấp {old_level}, móc {old_hook}/4 → "
            f"Cấp {item['level']}, móc {item['hook']}/4"
        )
        if new_interval_hours > 0:
            st.info(f"⏰ Móc tiếp theo: **{format_hours(new_interval_hours)}**")

        if old_level < item["level"]:
            st.balloons()
            st.success(f"🎉 Đã lên Cấp {item['level']}!")

        if item["level"] == 5 and item["hook"] == 4:
            st.success("🏆 Từ này đã đạt Cấp 5 — Móc 4!")
    else:
        st.error("❌ Chưa chính xác.")
        st.warning(f"Đáp án đúng: **{correct_ans_text}**")
        st.warning(
            f"📉 Cấp {old_level}, móc {old_hook}/4 → "
            f"Cấp {item['level']}, móc {item['hook']}/4"
        )
        if new_interval_hours > 0:
            st.info(f"🔄 Móc mới: **{format_hours(new_interval_hours)}**")

    save_deck()

    st.session_state.review_item = None
    st.session_state.q_type = None
    st.session_state.q_data = {}
    st.session_state.review_start_time = 0

    time.sleep(0.8)
    st.rerun()


# ============================================================
# 22. RESET ALL
# ============================================================

def reset_all_to_level_zero():
    for item in st.session_state.deck:
        item["level"] = 0
        item["hook"] = 0
        item["interval"] = 0
        item["next_review"] = datetime.now()
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
# 23. XỬ LÝ QUÁ HẠN
# ============================================================

process_overdue_items()


# ============================================================
# 24. HEADER
# ============================================================

st.title("🍌 MochiVocab")
st.caption("Dynamic Golden Time • Học theo cấp và 4 móc ghi nhớ")

now = datetime.now()
due_count = sum(
    1 for x in st.session_state.deck
    if x.get("next_review") and x["next_review"] <= now
)

tab_options = ["⏰ Ôn Tập", "🔍 Tra Từ Mới", "📋 Sổ Tay"]
tab_labels = {
    "⏰ Ôn Tập": f"⏰ Ôn Tập ({due_count})",
    "🔍 Tra Từ Mới": "🔍 Tra Từ Mới",
    "📋 Sổ Tay": f"📋 Sổ Tay ({len(st.session_state.deck)})",
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
# 25. TAB ÔN TẬP
# ============================================================

if selected_tab == "⏰ Ôn Tập":

    st.subheader("⏰ Ôn tập đúng Thời Điểm Vàng")

    now = datetime.now()
    due_items = [
        x for x in st.session_state.deck
        if x.get("next_review") and x["next_review"] <= now
    ]

    if not st.session_state.deck:
        st.warning("📚 Sổ tay đang trống.")
        st.write("Hãy sang **🔍 Tra Từ Mới** để thêm từ.")

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
            next_item["next_review"] - datetime.now()
        ).total_seconds()

        st.success("🎉 Hiện tại không có từ nào đến Thời Điểm Vàng.")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Từ tiếp theo", next_item["word"].upper())
        with col2:
            st.metric("Cấp", next_item["level"])

        st.info(f"⏰ Còn khoảng **{format_remaining(remaining)}**")

        remaining_seconds = max(0, int(remaining))

        st.components.v1.html(
            f"""
            <div style="
                text-align:center;
                background:#262730;
                color:#00FF66;
                padding:20px;
                border-radius:15px;
                margin-top:15px;
                box-sizing:border-box;
            ">
                <div style="font-size:13px; color:#AAAAAA; margin-bottom:8px;">
                    THỜI ĐIỂM VÀNG TIẾP THEO
                </div>
                <div id="mochi-countdown" style="font-size:30px; font-weight:bold; font-family:monospace;">
                    --:--:--
                </div>
            </div>

            <script>
                let remaining = {remaining_seconds};
                let reloaded = false;

                function updateCountdown() {{
                    const countdown = document.getElementById("mochi-countdown");
                    if (!countdown) return;

                    if (remaining <= 0) {{
                        countdown.innerText = "🔥 ĐÃ ĐẾN GIỜ!";
                        if (!reloaded) {{
                            reloaded = true;
                            setTimeout(function() {{
                                window.parent.location.reload();
                            }}, 1000);
                        }}
                        return;
                    }}

                    const days = Math.floor(remaining / 86400);
                    const hours = Math.floor((remaining % 86400) / 3600);
                    const minutes = Math.floor((remaining % 3600) / 60);
                    const seconds = remaining % 60;

                    let result = "";
                    if (days > 0) {{
                        result = days + " ngày " + String(hours).padStart(2, "0") + ":" + String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
                    }} else {{
                        result = String(hours).padStart(2, "0") + ":" + String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
                    }}

                    countdown.innerText = result;
                    remaining--;
                }}

                updateCountdown();
                setInterval(updateCountdown, 1000);
            </script>
            """,
            height=120
        )

    else:
        if not st.session_state.review_started:
            st.success(f"🔥 Có **{len(due_items)} từ** đang đến Thời Điểm Vàng.")
            st.markdown("---")
            st.markdown(
                """
                ### 🧠 Sẵn sàng ôn tập?

                MochiVocab sẽ chọn một từ đang đến giờ và bắt đầu tính thời gian phản hồi.
                """
            )

            if st.button("▶️ BẮT ĐẦU ÔN TẬP", type="primary", use_container_width=True, key="start_review"):
                min_level = min(x.get("level", 0) for x in due_items)
                candidates = [x for x in due_items if x.get("level", 0) == min_level]
                item = random.choice(candidates)

                st.session_state.review_started = True
                prepare_review_question(item)
                st.rerun()

        else:
            current_item = st.session_state.review_item

            if current_item is None:
                min_level = min(x.get("level", 0) for x in due_items)
                candidates = [x for x in due_items if x.get("level", 0) == min_level]
                item = random.choice(candidates)
                prepare_review_question(item)
                st.rerun()

            item = st.session_state.review_item
            q_type = st.session_state.q_type
            q_data = st.session_state.q_data

            if st.button("⏹️ Dừng ôn tập", key="stop_review"):
                st.session_state.review_started = False
                st.session_state.review_item = None
                st.session_state.q_type = None
                st.session_state.q_data = {}
                st.session_state.review_start_time = 0
                st.rerun()

            level = int(item.get("level", 0))
            hook = int(item.get("hook", 0))
            progress = hook / 4 if level > 0 else 0

            st.progress(progress)

            col1, col2 = st.columns(2)
            with col1:
                st.caption(get_level_name(level))
            with col2:
                st.caption(f"Móc: {hook}/4" if level > 0 else "Móc: 0/4")

            if level == 0:
                st.caption("⏰ Khoảng ôn: **0 giờ — Từ mới**")
            else:
                current_hours = get_current_interval(item)
                st.caption(f"📐 Móc hiện tại: **{format_hours(current_hours)}**")

            st.markdown("---")

            # CHOICE MEANING
            if q_type == "CHOICE_MEANING":
                st.markdown("### 🎲 TRẮC NGHIỆM CHỌN NGHĨA")
                st.info(f"Từ: **{item['word'].upper()}** `{item.get('phonetic', '')}`")

                if st.button("🔊 Nghe", key="choice_audio"):
                    play_audio_script(item["word"])

                st.write("Chọn nghĩa tiếng Việt:")
                for index, option in enumerate(q_data.get("options", [])):
                    if st.button(option, key=f"choice_{item['id']}_{index}"):
                        process_answer(
                            option.strip().lower() == item["meaning"].strip().lower(),
                            item["meaning"]
                        )

            # FILL BLANK (ĐÃ THÊM GỢI Ý KÝ TỰ THEO MÓC)
            elif q_type == "FILL_BLANK":
                st.markdown("### ✏️ ĐIỀN TỪ VÀO CHỖ TRỐNG")
                st.info(f"**{q_data.get('sentence', '')}**")

                # Hiển thị gợi ý chuỗi chữ cái dựa theo móc
                hint_pattern = q_data.get("hint_pattern", "")
                if hint_pattern:
                    st.markdown(
                        f"""
                        <div style="
                            background-color: #0e1117;
                            color: #00e676;
                            padding: 12px;
                            border-radius: 8px;
                            text-align: center;
                            font-family: monospace;
                            font-size: 22px;
                            font-weight: bold;
                            letter-spacing: 4px;
                            margin-bottom: 15px;
                            border: 1px dashed #00e676;
                        ">
                            💡 Gợi ý: {hint_pattern}
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                st.caption("Điền từ tiếng Anh còn thiếu.")

                user_ans = st.text_input("Từ còn thiếu:", key=f"fill_{item['id']}")

                if st.button("Xác Nhận", type="primary", key=f"fill_submit_{item['id']}"):
                    process_answer(
                        user_ans.strip().lower() == item["word"].strip().lower(),
                        item["word"].upper()
                    )

            # SPELLING
            elif q_type == "SPELLING":
                st.markdown("### ✍️ LUYỆN CHÍNH TẢ")
                st.info(f"Nghĩa tiếng Việt: **{item['meaning'].upper()}**")

                user_ans = st.text_input("Gõ từ tiếng Anh:", key=f"spell_{item['id']}")

                if st.button("Xác Nhận", type="primary", key=f"spell_submit_{item['id']}"):
                    process_answer(
                        user_ans.strip().lower() == item["word"].strip().lower(),
                        item["word"].upper()
                    )

            # CONTEXT
            elif q_type == "CONTEXT_MATCH":
                st.markdown("### 🧠 NGHĨA THEO NGỮ CẢNH")
                st.info(f'"{q_data.get("context", "")}"')
                st.write(f'Từ **{item["word"].upper()}** có nghĩa là gì?')

                for index, option in enumerate(q_data.get("options", [])):
                    if st.button(option, key=f"context_{item['id']}_{index}"):
                        process_answer(
                            option.strip().lower() == item["meaning"].strip().lower(),
                            item["meaning"]
                        )

            # TRUE / FALSE
            elif q_type == "FLASHCARD_TRUE_FALSE":
                st.markdown("### ⚡ FLASHCARD PHẢN XẠ")
                st.info(f"Từ: **{item['word']}**\n\nNghĩa: **{q_data.get('disp_meaning', '')}**")
                st.write("Thông tin trên đúng hay sai?")

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ ĐÚNG", type="primary", key=f"true_{item['id']}"):
                        process_answer(q_data["is_true"], "ĐÚNG" if q_data["is_true"] else "SAI")
                with col2:
                    if st.button("❌ SAI", key=f"false_{item['id']}"):
                        process_answer(not q_data["is_true"], "SAI" if not q_data["is_true"] else "ĐÚNG")

            # MEANING CHOICE
            elif q_type == "MEANING_CHOICE":
                st.markdown("### 🔤 NGHĨA → CHỌN TỪ TIẾNG ANH")
                st.info(f"Nghĩa: **{q_data.get('question', '').upper()}**")
                st.write("Chọn từ tiếng Anh:")

                for index, option in enumerate(q_data.get("options", [])):
                    if st.button(option.upper(), key=f"mchoice_{item['id']}_{index}"):
                        process_answer(
                            option.strip().lower() == item["word"].strip().lower(),
                            item["word"].upper()
                        )


# ============================================================
# 26. TAB TRA TỪ MỚI
# ============================================================

elif selected_tab == "🔍 Tra Từ Mới":

    st.subheader("🔍 Tra cứu & Thêm từ mới")

    word_input = st.text_input(
        "Nhập từ tiếng Anh:",
        placeholder="Ví dụ: resilience, innovate, discuss..."
    ).strip().lower()

    if st.button("🔎 Tra Từ", type="primary"):
        if word_input:
            with st.spinner("Đang tra từ và lấy bản dịch..."):
                data = fetch_word_full_data(word_input)

            if not data.get("success", False):
                st.error(f"❌ Không tìm thấy **{word_input}**.")
                st.session_state.temp_word = None
            else:
                examples = data.get("examples", [])
                example = examples[0] if examples else f"It is important to understand {word_input}."

                st.session_state.temp_word = {
                    "word": word_input,
                    "phonetic": data.get("phonetic", ""),
                    "meaning": data.get("short_vn", ""),
                    "example": example,
                }

    data = st.session_state.get("temp_word")

    if data is not None and isinstance(data, dict) and data.get("word", "") == word_input:
        st.markdown("---")
        st.info(f"**{data.get('word', '').upper()}** `{data.get('phonetic', '')}`")

        meaning_value = data.get("meaning", "").strip()

        if meaning_value:
            st.success(f"👉 **Nghĩa tiếng Việt:** {meaning_value}")
        else:
            st.warning("⚠️ Chưa lấy được bản dịch tiếng Việt.")
            manual_meaning = st.text_input(
                "Nhập nghĩa tiếng Việt:",
                key=f"manual_meaning_{data['word']}",
                placeholder="Ví dụ: khả năng phục hồi"
            )

            if manual_meaning.strip():
                data["meaning"] = manual_meaning.strip()
                st.session_state.temp_word = data
                st.success("✅ Đã cập nhật nghĩa.")

        st.caption(f"💡 Ví dụ: {data.get('example', '')}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔊 Nghe", key="new_word_audio"):
                play_audio_script(data["word"])

        with col2:
            if st.button("➕ Thêm vào Sổ Tay", key="add_new_word"):
                exists = any(
                    x.get("word", "").strip().lower() == data["word"].strip().lower()
                    for x in st.session_state.deck
                )

                if exists:
                    st.warning("⚠️ Từ này đã có trong Sổ Tay.")
                elif not data.get("meaning", "").strip():
                    st.error("⚠️ Bạn cần có nghĩa tiếng Việt trước khi thêm từ.")
                else:
                    new_item = {
                        "id": get_next_id(),
                        "word": data["word"],
                        "phonetic": data.get("phonetic", ""),
                        "meaning": data.get("meaning", ""),
                        "example": data.get("example", ""),
                        "level": 0,
                        "hook": 0,
                        "interval": 0,
                        "review_count": 0,
                        "correct_count": 0,
                        "wrong_count": 0,
                        "last_response_time": None,
                        "last_result": None,
                        "next_review": datetime.now(),
                        "_overdue_processed": False,
                    }

                    st.session_state.deck.append(new_item)
                    save_deck()

                    st.success(f"✅ Đã thêm **{data['word'].upper()}**")
                    st.info("🆕 Từ mới bắt đầu **Cấp 0 — 0 giờ**.")

                    time.sleep(0.5)
                    st.rerun()


# ============================================================
# 27. TAB SỔ TAY
# ============================================================

elif selected_tab == "📋 Sổ Tay":

    st.subheader("📋 Sổ tay từ vựng")

    if st.session_state.deck:
        total = len(st.session_state.deck)
        due = sum(
            1 for x in st.session_state.deck
            if x.get("next_review") and x["next_review"] <= datetime.now()
        )
        mastered = sum(
            1 for x in st.session_state.deck
            if x.get("level", 0) == 5 and x.get("hook", 0) == 4
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Tổng từ", total)
        with col2:
            st.metric("Cần ôn", due)
        with col3:
            st.metric("Cấp 5 • Móc 4", mastered)

        st.markdown("---")

        table_data = []
        for item in st.session_state.deck:
            next_review = item.get("next_review")
            if isinstance(next_review, datetime):
                remaining = (next_review - datetime.now()).total_seconds()
            else:
                remaining = 0

            if remaining <= 0:
                status = "🔥 Sẵn sàng ôn!"
            else:
                status = f"⏳ {format_remaining(remaining)}"

            correct_count = int(item.get("correct_count", 0))
            wrong_count = int(item.get("wrong_count", 0))
            accuracy_total = correct_count + wrong_count

            if accuracy_total > 0:
                accuracy_text = f"{correct_count / accuracy_total * 100:.0f}%"
            else:
                accuracy_text = "—"

            level = int(item.get("level", 0))
            hook = int(item.get("hook", 0))

            if level == 0:
                hook_text = "Cấp 0"
                interval_text = "0 giờ"
            else:
                hook_text = f"Cấp {level} • Móc {hook}/4"
                interval_text = format_hours(get_current_interval(item))

            table_data.append({
                "Từ": item.get("word", "").upper(),
                "Nghĩa": item.get("meaning", ""),
                "Cấp": hook_text,
                "Trạng thái": get_level_name(level),
                "Móc": interval_text,
                "Độ chính xác": accuracy_text,
                "Số lần ôn": item.get("review_count", 0),
                "Tiếp theo": status,
            })

        st.dataframe(table_data, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("### 📐 Hệ thống Thời Điểm Vàng")

        hook_table = {
            "Cấp 0": "0h — Từ mới",
            "Cấp 1": "1h → 4h → 12h → 24h",
            "Cấp 2": "25h → 28h → 36h → 48h",
            "Cấp 3": "49h → 52h → 60h → 72h",
            "Cấp 4": "73h → 76h → 84h → 96h",
            "Cấp 5": "97h → 100h → 108h → 120h",
        }

        st.table([
            {"Cấp": level_name, "Các móc": hooks}
            for level_name, hooks in hook_table.items()
        ])

        st.caption("💡 Đúng: tiến 1 móc. Sai: lùi 1 móc. Móc 1 Cấp 1 sai vẫn ở Cấp 1.")

        st.markdown("---")
        st.markdown("### 🔄 Đặt lại toàn bộ")
        st.warning("Thao tác này sẽ đưa tất cả từ về **Cấp 0 — 0 giờ** và xóa toàn bộ lịch sử ôn tập.")

        if st.button("🔄 RESET ALL VỀ CẤP 0", type="secondary", use_container_width=True, key="reset_all_words"):
            reset_all_to_level_zero()
            st.success("✅ Đã reset toàn bộ từ về Cấp 0.")
            time.sleep(0.5)
            st.rerun()

        st.markdown("---")

        if st.button("🗑️ Xóa toàn bộ từ vựng", key="delete_all_words"):
            st.session_state.deck = []
            st.session_state.review_item = None
            st.session_state.review_started = False
            st.session_state.q_type = None
            st.session_state.q_data = {}
            st.session_state.temp_word = None

            save_deck()
            st.success("Đã xóa toàn bộ dữ liệu.")
            time.sleep(0.5)
            st.rerun()

    else:
        st.info("📚 Sổ tay đang trống.")


# ============================================================
# 28. FOOTER
# ============================================================

st.markdown("---")
st.caption("🍌 MochiVocab • Dynamic Golden Time")
