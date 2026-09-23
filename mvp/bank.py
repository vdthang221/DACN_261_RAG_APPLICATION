"""Versioned problem XML and Moodle single-answer MCQ interchange."""
import json
import re
import xml.etree.ElementTree as ET

SKILLS = {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"}
BLOOMS = {"REMEMBER", "UNDERSTAND", "APPLY", "ANALYZE", "EVALUATE", "CREATE"}


def required_text(value, name, maximum=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name}: cần chuỗi không rỗng, tối đa {maximum} ký tự.")
    return value


def validate_problem(p):
    if not isinstance(p, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", p.get("id", "")):
        raise ValueError("ID bài toán phải là slug, tối đa 64 ký tự.")
    for key in ["title", "topic", "difficulty", "description", "starter", "solution"]:
        required_text(p.get(key), key, 200 if key in {"title", "topic", "difficulty"} else 12000)
    if p["difficulty"] not in {"Dễ", "Trung bình", "Khó"}:
        raise ValueError("Độ khó phải là Dễ, Trung bình hoặc Khó.")
    if not isinstance(p.get("skills"), list) or not p["skills"] or any(s not in SKILLS for s in p["skills"]):
        raise ValueError("Kỹ năng bài toán phải thuộc S1–S9.")
    if p.get("bloom") not in BLOOMS:
        raise ValueError("Mức Bloom không hợp lệ.")
    if not isinstance(p.get("tests"), list) or not 1 <= len(p["tests"]) <= 12:
        raise ValueError("Mỗi bài cần 1–12 testcase.")
    for test in p["tests"]:
        if not isinstance(test, dict):
            raise ValueError("Testcase không hợp lệ.")
        for key in ["input", "expected"]:
            if not isinstance(test.get(key), str) or len(test[key]) > 4000:
                raise ValueError("Input/output phải là chuỗi tối đa 4000 ký tự.")
    return p


def validate_mcqs(questions, problem, count=None):
    if not isinstance(questions, list) or not 1 <= len(questions) <= 20 or (count is not None and len(questions) != count):
        raise ValueError("Số lượng MCQ không hợp lệ.")
    for q in questions:
        if not isinstance(q, dict):
            raise ValueError("MCQ không hợp lệ.")
        required_text(q.get("question"), "Câu hỏi", 2000)
        if not isinstance(q.get("options"), list) or len(q["options"]) != 4:
            raise ValueError("Mỗi MCQ cần 4 phương án.")
        for option in q["options"]:
            required_text(option, "Phương án", 1000)
        if len(set(q["options"])) != 4 or type(q.get("answer")) is not int or not 0 <= q["answer"] < 4:
            raise ValueError("Phương án trùng hoặc đáp án không hợp lệ.")
        if q.get("skill") not in problem["skills"] or q.get("bloom") != problem["bloom"]:
            raise ValueError("MCQ nằm ngoài kỹ năng / mức độ của bài toán.")
        required_text(q.get("explanation"), "Giải thích", 3000)
    return questions


def parse_xml(raw, problems):
    if not isinstance(raw, str) or len(raw.encode()) > 512000:
        raise ValueError("XML tối đa 500 KB.")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("XML không được chứa DTD/entity.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("XML không hợp lệ.") from exc
    if root.tag == "problem-bank" and root.get("version") == "1":
        output = []
        for node in root.findall("problem"):
            p = {key: node.findtext(key, "") for key in ["title", "topic", "difficulty", "description", "starter", "solution", "bloom"]}
            p["id"] = node.get("id", "")
            p["skills"] = [s.text or "" for s in node.findall("skills/skill")]
            p["tests"] = [{"input": t.findtext("input", ""), "expected": t.findtext("expected", "")} for t in node.findall("tests/test")]
            output.append(validate_problem(p))
        if not 1 <= len(output) <= 100 or len({p["id"] for p in output}) != len(output):
            raise ValueError("Cần 1–100 bài toán với ID duy nhất.")
        return "problems", output
    if root.tag == "quiz":
        output = []
        for node in root.findall("question"):
            if node.get("type") == "category":
                continue
            if node.get("type") != "multichoice" or node.findtext("single", "true").lower() != "true":
                raise ValueError("Chỉ hỗ trợ Moodle multichoice có một đáp án đúng.")
            tags = [t.text or "" for t in node.findall("tags/tag/text")]
            meta = dict(tag.split(":", 1) for tag in tags if ":" in tag)
            pid = meta.get("problem")
            if pid not in problems:
                raise ValueError("Moodle cần tag problem:<id> trỏ tới bài toán đã có.")
            answers = node.findall("answer")
            fractions = [a.get("fraction", "0") for a in answers]
            if fractions.count("100") != 1 or any(f not in {"0", "100"} for f in fractions):
                raise ValueError("Moodle cần đúng một answer fraction=100; còn lại bằng 0.")
            q = {"question": node.findtext("questiontext/text", ""), "options": [a.findtext("text", "") for a in answers],
                 "answer": fractions.index("100"), "skill": meta.get("skill"), "bloom": meta.get("bloom"),
                 "explanation": node.findtext("generalfeedback/text", ""), "problem_id": pid}
            # HTML is treated as plain text, never rendered as executable markup.
            validate_mcqs([q], problems[pid])
            output.append(q)
        if not 1 <= len(output) <= 200:
            raise ValueError("Cần 1–200 MCQ.")
        return "mcqs", output
    raise ValueError("Cần problem-bank version=1 hoặc Moodle quiz.")


def problem_xml(problems):
    root = ET.Element("problem-bank", version="1")
    for p in problems:
        node = ET.SubElement(root, "problem", id=p["id"])
        for key in ["title", "topic", "difficulty", "description", "starter", "solution", "bloom"]:
            ET.SubElement(node, key).text = p[key]
        skills = ET.SubElement(node, "skills")
        for skill in p["skills"]:
            ET.SubElement(skills, "skill").text = skill
        tests = ET.SubElement(node, "tests")
        for test in p["tests"]:
            t = ET.SubElement(tests, "test")
            for key in ["input", "expected"]:
                ET.SubElement(t, key).text = test[key]
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def moodle_xml(questions):
    root = ET.Element("quiz")
    for index, q in enumerate(questions, 1):
        node = ET.SubElement(root, "question", type="multichoice")
        ET.SubElement(ET.SubElement(node, "name"), "text").text = f"{q['problem_id']} / {index}"
        for key, value in [("questiontext", q["question"]), ("generalfeedback", q["explanation"])]:
            ET.SubElement(ET.SubElement(node, key, format="plain_text"), "text").text = value
        ET.SubElement(node, "single").text = "true"
        for i, value in enumerate(q["options"]):
            ET.SubElement(ET.SubElement(node, "answer", fraction="100" if i == q["answer"] else "0", format="plain_text"), "text").text = value
        tags = ET.SubElement(node, "tags")
        for value in [f"problem:{q['problem_id']}", f"skill:{q['skill']}", f"bloom:{q['bloom']}"]:
            ET.SubElement(ET.SubElement(tags, "tag"), "text").text = value
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
