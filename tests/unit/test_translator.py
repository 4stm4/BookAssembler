"""Whole-book translation (RFC 0021 §2, §5.1): units, resume, agents.

"Programming the Z80" is 630 pages, some 7200 paragraphs: tens of hours of a
7B model on the edge cluster, a few on the GPU. A job that long stops — a
deploy, a GPU session that ran out — so what it did has to stay done, and
what it could not do must not come out as a "translation" in English.
"""
import threading
import time

import pytest

from src.assembler import translator as T
from src.assembler.latex_builder import build_latex
from src.krm.models import (
    CodeBlock,
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    TocEntryBlock,
    VisualLayout,
)

RU = "Russian"
EDGE = T.Target("edge", "http://edge", "qwen2.5:7b")


def para(*lines, page=0):
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=l)]) for l in lines],
        visual_layout=VisualLayout(bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.2),
                                   page_or_screen_index=page),
    )


def book(*children):
    return KnowledgeDocument(title="zaks", root_containers=[
        ContainerUnit(title="", level=1, children=list(children))])


def source_of(prompt):
    return prompt.split("Text:\n", 1)[1]


def russian(text):
    return "Перевод: " + " ".join(["слово"] * max(1, len(text) // 6))


@pytest.fixture()
def agent(monkeypatch):
    """A well-behaved agent: Russian of about the source's length."""
    calls = []

    def call(target, prompt):
        calls.append((target.name, source_of(prompt)))
        return russian(source_of(prompt))

    monkeypatch.setattr(T, "_call_target", call)
    return calls


def seg(block):
    return block.metadata["translations"][RU]


class TestSourceText:
    def test_a_word_hyphenated_at_the_line_end_is_whole_again(self):
        p = para("the stack pointer must be in-", "cremented by one.")
        assert T.source_text("paragraph", p) == "the stack pointer must be incremented by one."

    def test_a_hyphen_before_a_capital_stays(self):
        assert T.join_lines(["the IX-", "Register"]) == "the IX- Register"

    def test_spans_keep_their_own_spaces(self):
        line = TextLineInline(spans=[StyledTextSpan(text="LD "), StyledTextSpan(text="A"),
                                     StyledTextSpan(text=",(HL)")])
        assert T._line_text(line) == "LD A,(HL)"

    def test_two_spans_that_would_glue_two_words_get_a_space(self):
        line = TextLineInline(spans=[StyledTextSpan(text="IX"), StyledTextSpan(text="IY")])
        assert T._line_text(line) == "IX IY"


class TestUnits:
    def test_a_sentence_cut_by_the_page_break_is_one_unit(self):
        head = para("(In other microprocessors, the stack pointer points just above the", page=16)
        tail = para("last actual entry.)", page=17)
        [unit] = T.collect_units(book(head, tail))
        assert unit.blocks == [head, tail]
        assert unit.text.endswith("points just above the last actual entry.)")

    def test_a_word_cut_by_the_page_break_is_whole_again(self):
        [unit] = T.collect_units(book(para("must be in-", page=3), para("cremented by one.", page=4)))
        assert unit.text == "must be incremented by one."

    @pytest.mark.parametrize("first, second, pages", [
        ("The sentence ends here.", "and this is lower case", (3, 4)),
        ("no end of sentence", "But this starts a new one.", (3, 4)),
        ("no end of sentence", "and lower case", (3, 3)),
        ("no end of sentence", "and lower case", (3, 5)),
    ])
    def test_otherwise_paragraphs_stay_apart(self, first, second, pages):
        units = T.collect_units(book(para(first, page=pages[0]), para(second, page=pages[1])))
        assert len(units) == 2

    def test_headings_and_contents_entries_are_translated(self):
        entry = TocEntryBlock(entry_text="Registers and Flags", chapter_number="1.2")
        chapter = ContainerUnit(title="THE STACK", level=1, children=[entry])
        doc = KnowledgeDocument(title="zaks", root_containers=[chapter])
        assert [(u.kind, u.text) for u in T.collect_units(doc)] == [
            ("title", "THE STACK"), ("toc", "Registers and Flags")]

    def test_code_goes_through_as_it_is(self):
        """RFC 0021 §2.3: atomic blocks are not translated."""
        assert T.collect_units(book(CodeBlock(code_text="LD A,(HL)\nINC HL"))) == []

    def test_a_line_of_numbers_is_not_sent(self):
        assert T.collect_units(book(para("0100 3E 10"))) == []


class TestJob:
    def test_every_unit_is_translated_once(self, agent):
        a, b = para("The accumulator holds the result."), para("The flags record its properties.")
        stats = T.translate_document(book(a, b), RU, [EDGE])
        assert (stats.total, stats.done, stats.failed, stats.left) == (2, 2, 0, 0)
        assert len(agent) == 2
        assert seg(a)["target_text"].startswith("слово")  # "Перевод:" is not the translation

    def test_nothing_done_is_sent_again(self, agent):
        doc = book(para("The accumulator holds the result."), para("The flags record it."))
        T.translate_document(doc, RU, [EDGE])
        agent.clear()
        stats = T.translate_document(doc, RU, [EDGE])
        assert agent == []
        assert (stats.cached, stats.done) == (2, 0)

    def test_a_changed_source_is_translated_again(self, agent):
        p = para("The accumulator holds the result.")
        doc = book(p, para("The flags record it."))
        T.translate_document(doc, RU, [EDGE])
        p.inlines[0].spans[0].text = "The accumulator holds the sum."
        agent.clear()
        T.translate_document(doc, RU, [EDGE])
        assert agent == [("edge", "The accumulator holds the sum.")]

    def test_no_reply_records_nothing(self, monkeypatch):
        monkeypatch.setattr(T, "_call_target", lambda target, prompt: None)
        p = para("The accumulator holds the result of every operation.")
        stats = T.translate_document(book(p), RU, [EDGE])
        assert stats.failed == 1
        assert "translations" not in (p.metadata or {})

    def test_the_source_echoed_back_is_not_a_translation(self, monkeypatch):
        monkeypatch.setattr(T, "_call_target", lambda target, prompt: source_of(prompt))
        p = para("The accumulator holds the result of every operation.")
        T.translate_document(book(p), RU, [EDGE])
        assert "translations" not in (p.metadata or {})
        # So the book shows the English it has, not English called Russian.
        assert "accumulator holds" in build_latex(book(p), RU)

    def test_what_one_agent_failed_another_does(self, monkeypatch):
        def call(target, prompt):
            return None if target.name == "dead" else russian(source_of(prompt))
        monkeypatch.setattr(T, "_call_target", call)
        blocks = [para(f"Paragraph number {i} of the chapter on the stack.") for i in range(6)]
        stats = T.translate_document(book(*blocks), RU,
                                     [T.Target("dead", "http://dead", "m"), EDGE])
        assert (stats.done, stats.failed, stats.left) == (6, 0, 0)
        assert {seg(b)["transformation"]["agent"] for b in blocks} == {"edge"}

    def test_an_agent_that_keeps_failing_leaves_the_job(self, monkeypatch):
        monkeypatch.setattr(T, "_call_target", lambda target, prompt: None)
        blocks = [para(f"Paragraph number {i} of the chapter on the stack.") for i in range(3)]
        stats = T.translate_document(book(*blocks), RU, [EDGE])
        # Five failures in a row and the only worker is gone; the units are
        # left for the next start, not given up on.
        assert (stats.done, stats.failed, stats.left) == (0, 0, 3)

    def test_a_stopped_job_leaves_the_rest_for_the_next_start(self, agent):
        stop = threading.Event()
        stop.set()
        stats = T.translate_document(book(para("One sentence here."), para("Another one.")), RU,
                                     [EDGE], stop=stop)
        assert (stats.done, stats.left) == (0, 2)
        assert agent == []

    def test_the_segment_names_the_prompt_the_agent_and_the_model(self, agent):
        p = para("The accumulator holds the result.")
        T.translate_document(book(p), RU, [EDGE])
        s = seg(p)
        prompt = T._build_translate_prompt("The accumulator holds the result.", RU)
        assert s["transformation"]["prompt_hash"] == T._sha(prompt)
        assert (s["transformation"]["agent"], s["transformation"]["model"]) == ("edge", "qwen2.5:7b")
        assert s["source_text"] == "The accumulator holds the result."

    def test_the_continued_block_renders_nothing_of_its_own(self, agent):
        head = para("(In other microprocessors, the stack pointer points just above the", page=16)
        tail = para("last actual entry.)", page=17)
        doc = book(head, tail)
        T.translate_document(doc, RU, [EDGE])
        assert seg(tail) ["merged_into"] == head.id
        assert seg(head)["merged_with"] == [tail.id]
        tex = build_latex(doc, RU)
        assert seg(head)["target_text"] in tex
        assert "last actual entry" not in tex


class TestRejection:
    def test_a_reply_in_another_script_is_rejected(self):
        assert T._rejection("The stack pointer.", "堆栈指针。", RU)

    def test_a_heading_left_in_english_is_rejected(self):
        assert T._rejection("INTRODUCTION", "INTRODUCTION", RU)

    def test_mnemonics_kept_as_they_are_are_fine(self):
        assert T._rejection("LD A,(HL)", "LD A,(HL)", RU) is None

    def test_a_reply_out_of_proportion_is_rejected(self):
        assert T._rejection("The stack pointer points to the top of the stack.", "Стек.", RU)

    def test_quotes_and_a_label_around_the_reply_are_dropped(self):
        assert T._cleaned('Перевод: "Указатель стека."', "The stack pointer.") == "Указатель стека."


class TestTargets:
    AGENTS = [
        {"name": "gpu", "host": "http://gpu", "kind": "managed", "roles": ["translate"]},
        {"name": "orangepi", "host": "http://o", "active_model": "m", "roles": ["translate"]},
        {"name": "rpi5", "host": "http://r", "active_model": "m", "roles": ["translate"]},
        {"name": "down", "host": "http://down", "roles": ["translate"]},
        {"name": "vision", "host": "http://v", "kind": "multimodel", "roles": ["vision"]},
    ]

    def test_a_reachable_gpu_takes_the_whole_book(self, monkeypatch):
        """RFC 0022 §7.2: the edge cluster is the fallback, and one model
        keeps one terminology through the book."""
        from src.agents import router
        monkeypatch.setattr(router, "load_agents", lambda: self.AGENTS)
        monkeypatch.setattr(router, "probe_managed",
                            lambda host: (True, {"runner": "up", "tasks": ["qwen"]}))
        monkeypatch.setattr(router, "_probe_ollama",
                            lambda host: (host != "http://down", ["m"]))
        assert [t.name for t in T.translation_targets()] == ["gpu"] * T.GPU_WORKERS

    def test_without_a_gpu_each_reachable_ollama_is_one_worker(self, monkeypatch):
        from src.agents import router
        monkeypatch.setattr(router, "load_agents", lambda: self.AGENTS)
        monkeypatch.setattr(router, "probe_managed", lambda host: (False, {}))
        monkeypatch.setattr(router, "_probe_ollama",
                            lambda host: (host != "http://down", ["m"]))
        assert [t.name for t in T.translation_targets()] == ["orangepi", "rpi5"]

    def test_a_manager_without_a_running_runner_is_not_a_target(self, monkeypatch):
        from src.agents import router
        monkeypatch.setattr(router, "load_agents", lambda: [
            {"name": "gpu", "host": "http://gpu", "kind": "managed", "roles": ["translate"]},
            {"name": "rpi5", "host": "http://r", "roles": ["translate"]},
        ])
        monkeypatch.setattr(router, "probe_managed", lambda host: (True, {"runner": "down"}))
        monkeypatch.setattr(router, "_probe_ollama", lambda host: (True, ["m"]))
        assert [t.name for t in T.translation_targets()] == ["rpi5"]


class TestApi:
    """The job as the editor runs it: start, progress, saved to disk, resume."""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        pytest.importorskip("fastapi")
        import json

        from fastapi.testclient import TestClient

        monkeypatch.setenv("KAE_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(T, "translation_targets", lambda: [EDGE])
        job_id = "translate-job"
        lines = [{"text": "The stack pointer must be in-", "bbox": [0.1, 0.1, 0.9, 0.12]},
                 {"text": "cremented by one.", "bbox": [0.1, 0.12, 0.6, 0.14]}]
        para_json = {"id": "p-1", "type": "ParagraphBlock", "page_index": 3,
                     "text": "The stack pointer must be in- cremented by one.",
                     "bbox": [0.1, 0.1, 0.9, 0.14], "lines": lines, "confidence_score": 0.9}
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / f"{job_id}.json").write_text(json.dumps({
            "title": "zaks", "_source_uri": f"upload://{job_id}.pdf", "_source_type": "pdf",
            "page_count": 4,
            "containers": [{"id": "root", "type": "ContainerUnit", "title": "", "level": 1,
                            "children": [para_json]}],
        }))
        from src.api.app import create_app
        with TestClient(create_app()) as tc:
            yield tc, job_id, docs / f"{job_id}.json"

    @staticmethod
    def wait_done(tc, job_id):
        for _ in range(100):
            if tc.get(f"/api/v1/jobs/{job_id}/progress").json().get("stage") in ("done", "error"):
                return
            time.sleep(0.05)
        pytest.fail("translation did not finish")

    def test_the_translation_is_saved_and_a_second_start_resumes(self, client, agent):
        import json
        tc, job_id, path = client
        res = tc.post(f"/api/v1/jobs/{job_id}/translate/start", json={"target_lang": RU}).json()
        assert (res["total_units"], res["cached"], res["agents"]) == (1, 0, ["edge"])
        self.wait_done(tc, job_id)
        assert agent == [("edge", "The stack pointer must be incremented by one.")]

        saved = json.loads(path.read_text())["containers"][0]["children"][0]
        assert saved["metadata"]["translations"][RU]["target_text"].startswith("слово")

        again = tc.post(f"/api/v1/jobs/{job_id}/translate/start", json={"target_lang": RU}).json()
        assert again["cached"] == 1

    def test_the_book_is_not_assembled_while_it_is_being_translated(self, client, monkeypatch):
        tc, job_id, _ = client
        gate = threading.Event()

        def slow(target, prompt):
            gate.wait(5)
            return russian(source_of(prompt))

        monkeypatch.setattr(T, "_call_target", slow)
        tc.post(f"/api/v1/jobs/{job_id}/translate/start", json={"target_lang": RU})
        try:
            assert tc.post(f"/api/v1/jobs/{job_id}/assemble", json={"target_lang": RU}).status_code == 409
            assert tc.post(f"/api/v1/jobs/{job_id}/translate/start",
                           json={"target_lang": RU}).status_code == 409
        finally:
            gate.set()
        self.wait_done(tc, job_id)

    def test_when_the_gpu_session_ends_the_edge_carries_on(self, client, monkeypatch):
        """Kaggle's session ends mid-book: the GPU's workers leave the job and
        the edge cluster, reachable now, finishes it — nobody restarts it."""
        tc, job_id, _ = client
        gpu = T.Target("kaggle", "http://gpu", "qwen-vl", "multimodel")
        plan = iter([[gpu], [EDGE]])
        monkeypatch.setattr(T, "translation_targets", lambda: next(plan, [EDGE]))

        def call(target, prompt):
            return None if target.gpu else russian(source_of(prompt))

        monkeypatch.setattr(T, "_call_target", call)
        tc.post(f"/api/v1/jobs/{job_id}/translate/start", json={"target_lang": RU})
        self.wait_done(tc, job_id)
        assert tc.get(f"/api/v1/jobs/{job_id}/progress").json()["stage"] == "done"
        [para] = tc.get(f"/api/v1/jobs/{job_id}/result").json()["containers"][0]["children"]
        assert para["metadata"]["translations"][RU]["transformation"]["agent"] == "edge"

    def test_stop_without_a_running_job_is_404(self, client):
        tc, job_id, _ = client
        assert tc.post(f"/api/v1/jobs/{job_id}/translate/stop").status_code == 404
