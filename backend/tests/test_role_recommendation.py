import asyncio
import json
import os
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from config import ROLES_BY_CATEGORY, TARGET_ROLES
from api.routes.resume import EXTRACT_PROMPT, ResumeKeywordsRequest, extract_keywords

# Roles that must exist after the config.py expansion
EXPECTED_ROLES = [
    "Java Developer", ".NET Developer", "C# Developer", "C++ Developer",
    "Go Developer", "Rust Developer", "Kotlin Developer", "Swift Developer",
    "Node.js Developer", "React Developer", "Angular Developer", "Vue.js Developer",
    "PHP Developer", "Ruby Developer", "TypeScript Developer",
    "Backend Developer", "Frontend Developer", "Full Stack Engineer", "Software Developer",
    "iOS Developer", "Android Developer", "MLOps Engineer", "Computer Vision Engineer",
    "NLP Engineer", "Prompt Engineer", "Solutions Architect", "Cloud Architect",
    "Software Architect", "Enterprise Architect", "Cybersecurity Analyst",
    "Penetration Tester", "SDET", "SQL Developer", "Salesforce Developer",
    "WordPress Developer", "SAP Consultant", "Product Owner", "Agile Coach",
    "UX Researcher", "Aerospace Engineer", "Robotics Engineer", "FP&A Analyst",
]

SAMPLE_RESUME_JAVA = """Java Developer Resume

Software Engineer with 5 years of experience building enterprise applications in Java and Spring Boot.

TECHNICAL SKILLS
Java, Spring Boot, Hibernate, REST APIs, Microservices, SQL, PostgreSQL, Docker, Kubernetes, AWS, Maven, Git, JUnit, Kafka.

EXPERIENCE
Senior Java Developer — TechCorp (2020 - Present)
- Built scalable RESTful microservices serving 2M+ daily requests using Spring Boot and Kafka.
- Designed relational schemas in PostgreSQL and optimized slow queries reducing latency by 40%.
- Containerized services with Docker and deployed to AWS EKS.

Java Developer — FinServ (2018 - 2020)
- Developed core banking APIs in Java 11 with Spring Data JPA and OAuth2 security.
- Wrote unit and integration tests with JUnit and Mockito (90%+ coverage).

EDUCATION
B.S. Computer Science, University of Michigan
"""

SAMPLE_RESUME_MARKETING = """Digital Marketing Specialist Resume

DATA-DRIVEN MARKETER
Marketing professional with 4 years of experience in performance marketing, SEO, and email campaigns.

SKILLS
SEO, Google Ads, Meta Ads, Google Analytics, Email Marketing, Content Strategy, A/B Testing, HubSpot, Mailchimp.

EXPERIENCE
Digital Marketing Specialist — GrowCo (2021 - Present)
- Managed $50K monthly paid-media budget across Google and Meta, driving 3x ROAS.
- Grew organic traffic 80% through SEO and content strategy.
- Built automated email flows increasing conversions by 25%.

Social Media Coordinator — Startup (2019 - 2021)
- Ran social media campaigns and influencer partnerships.

EDUCATION
B.A. Marketing, NYU
"""


def _normalize(role: str) -> str:
    return re.sub(r"[^a-z0-9]", "", role.lower())


def _known_role(role: str):
    """Exact, then normalized match against TARGET_ROLES. Returns matched role or None."""
    if role in TARGET_ROLES:
        return role
    n = _normalize(role)
    for known in TARGET_ROLES:
        if _normalize(known) == n:
            return known
    return None


def _run_extract_keywords(llm_response: str, resume_text: str = "sample resume"):
    with patch("llm.llm_client.LLMClient.chat", return_value=llm_response):
        return asyncio.run(extract_keywords(ResumeKeywordsRequest(resume_text=resume_text)))


# ── 1. Config integrity (no LLM) ──

class TestRolesConfig(unittest.TestCase):
    def test_new_roles_present(self):
        missing = [r for r in EXPECTED_ROLES if r not in TARGET_ROLES]
        self.assertEqual(missing, [], f"Roles missing from TARGET_ROLES: {missing}")

    def test_no_duplicate_roles(self):
        dups = [r for r in set(TARGET_ROLES) if TARGET_ROLES.count(r) > 1]
        self.assertEqual(dups, [], f"Duplicate roles: {dups}")

    def test_flat_list_matches_categories(self):
        flat = [r for roles in ROLES_BY_CATEGORY.values() for r in roles]
        self.assertEqual(TARGET_ROLES, flat,
                         "TARGET_ROLES must be the flattened ROLES_BY_CATEGORY")

    def test_categories_nonempty(self):
        empty = [k for k, v in ROLES_BY_CATEGORY.items() if not v]
        self.assertEqual(empty, [], f"Empty categories: {empty}")

    def test_prompt_renders_with_new_roles(self):
        prompt = EXTRACT_PROMPT.format(
            available_roles=json.dumps(TARGET_ROLES),
            resume=SAMPLE_RESUME_JAVA,
        )
        self.assertIn("Java Developer", prompt)
        self.assertIn(".NET Developer", prompt)
        self.assertNotIn("{available_roles}", prompt)
        self.assertNotIn("{resume}", prompt)
        self.assertTrue(len(prompt) > 5000, "Role list unexpectedly small in prompt")


# ── 2. Endpoint parsing (mocked LLM) ──

class TestExtractKeywordsParsing(unittest.TestCase):
    def test_valid_response_parses(self):
        llm = '{"keywords": ["java", "spring boot"], "suggested_roles": ["Java Developer", "Backend Developer"]}'
        result = _run_extract_keywords(llm)
        self.assertEqual(result.suggested_roles, ["Java Developer", "Backend Developer"])
        self.assertEqual(len(result.keywords), 2)

    def test_malformed_response_returns_empty(self):
        result = _run_extract_keywords("not json at all")
        self.assertEqual(result.suggested_roles, [])

    def test_roles_limited_to_three(self):
        llm = json.dumps({"keywords": ["x"], "suggested_roles": ["a", "b", "c", "d", "e"]})
        result = _run_extract_keywords(llm)
        self.assertLessEqual(len(result.suggested_roles), 3)

    def test_keywords_limited_to_thirty(self):
        llm = json.dumps({"keywords": [f"kw{i}" for i in range(50)]})
        result = _run_extract_keywords(llm)
        self.assertLessEqual(len(result.keywords), 30)

    def test_empty_response_returns_empty(self):
        result = _run_extract_keywords("")
        self.assertEqual(result.suggested_roles, [])


# ── 3. Live AI recommendation (opt-in: RUN_LIVE=1) ──

def _live_call(resume_text: str):
    return asyncio.run(extract_keywords(ResumeKeywordsRequest(resume_text=resume_text)))


@unittest.skipUnless(os.environ.get("RUN_LIVE") == "1", "set RUN_LIVE=1 to call the real LLM")
class TestLiveRoleRecommendation(unittest.TestCase):
    def _check(self, resume_text: str, sample_name: str):
        result = _live_call(resume_text)
        roles = result.suggested_roles
        unmatched = [r for r in roles if _known_role(r) is None]
        print(f"\n[{sample_name}] suggested_roles={roles}")
        for r in roles:
            print(f"  - {r!r} -> {_known_role(r)!r}")
        self.assertTrue(roles, f"LLM returned no suggested roles for {sample_name}")
        self.assertEqual(unmatched, [], f"Roles not in TARGET_ROLES for {sample_name}: {unmatched}")

    def test_java_resume(self):
        self._check(SAMPLE_RESUME_JAVA, "java")

    def test_marketing_resume(self):
        self._check(SAMPLE_RESUME_MARKETING, "marketing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
