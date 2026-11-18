from src.modules.accessibility_ppt.engine.ppt_validator.reading_order_agent import (
    ReadingOrderAgent,
)


def test_object_order_is_reported_when_title_follows_body_text():
    agent = ReadingOrderAgent()
    context = {
        "slides": [
            {
                "title": "Overview",
                "shapes": [
                    {"text": "Body text first", "type": "body", "order": 2},
                    {"text": "Overview", "type": "title", "order": 1},
                ],
            }
        ]
    }

    issue = agent.run_check("PPT-READING-001", context)

    assert issue.rule_id == "PPT-READING-001"
    assert issue.status == "FAIL"
    assert "object order" in issue.message.lower()


def test_decorative_shape_before_content_is_reported_as_fail():
    agent = ReadingOrderAgent()
    context = {
        "slides": [
            {
                "title": "Agenda",
                "shapes": [
                    {"text": "Decorative background", "decorative": True, "order": 1},
                    {"text": "Agenda body", "decorative": False, "order": 2},
                ],
            }
        ]
    }

    issue = agent.run_check("PPT-READING-003", context)

    assert issue.rule_id == "PPT-READING-003"
    assert issue.status == "FAIL"
    assert "decorative" in issue.message.lower()


def test_z_order_issue_is_reported_when_shape_order_is_inconsistent():
    agent = ReadingOrderAgent()
    context = {
        "slides": [
            {
                "title": "Chart",
                "shapes": [
                    {"text": "Chart label", "z_order": 2},
                    {"text": "Chart title", "z_order": 1},
                ],
            }
        ]
    }

    issue = agent.run_check("PPT-READING-004", context)

    assert issue.rule_id == "PPT-READING-004"
    assert issue.status == "FAIL"
    assert "z-order" in issue.message.lower()
