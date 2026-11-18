from src.modules.accessibility_ppt.engine.ppt_validator.slide_strcture_agent import (
    SlideStructureAgent,
)


def test_missing_slide_title_is_reported_as_fail():
    agent = SlideStructureAgent()
    context = {
        "slides": [
            {
                "title": None,
                "shapes": [{"text": "Body text only"}],
            }
        ]
    }

    issue = agent.run_check("PPT-STRUCTURE-001", context)

    assert issue.rule_id == "PPT-STRUCTURE-001"
    assert issue.status == "FAIL"
    assert "title" in issue.message.lower()


def test_empty_slide_is_reported_as_fail():
    agent = SlideStructureAgent()
    context = {
        "slides": [
            {
                "title": "",
                "shapes": [],
            }
        ]
    }

    issue = agent.run_check("PPT-STRUCTURE-003", context)

    assert issue.rule_id == "PPT-STRUCTURE-003"
    assert issue.status == "FAIL"
    assert "empty" in issue.message.lower()


def test_placeholder_title_is_reported_as_fail():
    agent = SlideStructureAgent()
    context = {
        "slides": [
            {
                "title": "Click to add title",
                "shapes": [{"text": "Click to add title"}],
            }
        ]
    }

    issue = agent.run_check("PPT-STRUCTURE-002", context)

    assert issue.rule_id == "PPT-STRUCTURE-002"
    assert issue.status == "FAIL"
    assert "placeholder" in issue.message.lower()
