from core.conversation_manager import ConversationManager
from core.phrases import is_dismissal, parse_yes_no
from core.reply_format import guess_lang_from_script, parse_reply
from core.text_match import rank


def test_reply_with_tag_and_speak_block():
    r = parse_reply("[lang=ur-Latn] Gmail khol diya hai. <speak>جی میل کھول دیا ہے۔</speak>")
    assert r.lang == "ur-Latn"
    assert r.display == "Gmail khol diya hai."
    assert r.speech == "جی میل کھول دیا ہے۔"


def test_reply_without_tag_uses_script():
    assert parse_reply("میں نے ای میلز چیک کر لی ہیں").lang == "ur"
    assert parse_reply("मैंने ईमेल देख लिए हैं").lang == "hi"
    assert parse_reply("plain english", "en").lang == "en"
    assert guess_lang_from_script("تم فتح التطبيق", "ar") == "ar"
    assert guess_lang_from_script("アプリを開きました") == "ja"


def test_yes_no_multilingual_and_fail_safe():
    for yes in ["yes please", "haan kar do", "ji haan", "ہاں", "हाँ", "oui", "はい", "theek hai"]:
        assert parse_yes_no(yes) is True, yes
    for no in ["no", "nahi", "mat karo", "نہیں", "नहीं", "nein", "不要"]:
        assert parse_yes_no(no) is False, no
    assert parse_yes_no("no, go ahead") is False          # ambiguous -> no
    assert parse_yes_no("banana") is None


def test_dismissal_only_for_short_utterances():
    assert is_dismissal("bas shukriya")
    assert is_dismissal("that's all")
    assert not is_dismissal("thanks, now open Chrome and check my downloads")


def test_app_ranking_prefers_exact_app():
    names = ["Chrome Remote Desktop", "Google Chrome", "Slack", "Visual Studio Code"]
    assert names[rank("chrome", names)[0][0]] == "Google Chrome"
    assert names[rank("slack", names)[0][0]] == "Slack"


def test_conversation_trim_keeps_tool_pairs_intact():
    cm = ConversationManager(max_messages=6)
    for i in range(6):
        cm.add_user_text(f"q{i}")
        cm.add_assistant([{"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}])
        cm.add_tool_results([{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}])
        cm.add_assistant([{"type": "text", "text": "done"}])
    msgs = cm.messages()
    assert msgs[0]["role"] == "user" and msgs[0]["content"][0]["type"] == "text"
    ids_used = {b["id"] for m in msgs for b in m["content"] if b.get("type") == "tool_use"}
    ids_answered = {b["tool_use_id"] for m in msgs for b in m["content"] if b.get("type") == "tool_result"}
    assert ids_used == ids_answered


def test_consecutive_user_text_merges():
    cm = ConversationManager()
    cm.add_user_text("a")
    cm.add_user_text("b")
    assert len(cm.messages()) == 1 and len(cm.messages()[0]["content"]) == 2
