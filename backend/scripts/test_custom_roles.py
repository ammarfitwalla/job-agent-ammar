"""Tests for custom roles: title-case, DB persistence, dedup, delete."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db

RESULTS = []


def check(label, cond, detail=""):
    RESULTS.append(cond)
    tag = "PASS" if cond else "FAIL"
    extra = f"  [{detail}]" if detail else ""
    print(f"  {tag}  {label}{extra}")


def title_case(s):
    return " ".join(w.capitalize() for w in s.split())


def main():
    # Clean slate
    with db._get_conn() as (conn, cur):
        cur.execute("DELETE FROM custom_roles")

    # --- title-case formatting ---
    check("title_case single word", title_case("data analyst") == "Data Analyst")
    check("title_case multi word", title_case("ai ethics researcher") == "Ai Ethics Researcher")
    check("title_case already capitalized", title_case("UI/UX Designer") == "Ui/ux Designer")
    check("title_case leading spaces", title_case("  product manager") == "Product Manager")
    check("title_case mixed case input", title_case("sOFTwArE eNGINeer") == "Software Engineer")

    # --- add to DB ---
    ok = db.add_custom_role("Data Analyst")
    check("add first role returns True", ok)
    roles = db.get_custom_roles()
    check("get returns added role", roles == ["Data Analyst"], str(roles))

    # --- dedup (case-insensitive via COLLATE NOCASE) ---
    ok2 = db.add_custom_role("data analyst")
    check("duplicate (different case) returns False", not ok2)
    roles2 = db.get_custom_roles()
    check("dedup keeps one entry", len(roles2) == 1, str(roles2))

    # --- add more roles (sorted order) ---
    db.add_custom_role("Product Manager")
    db.add_custom_role("AI Engineer")
    roles3 = db.get_custom_roles()
    check("roles sorted alphabetically", roles3 == ["AI Engineer", "Data Analyst", "Product Manager"], str(roles3))

    # --- empty / whitespace ---
    ok3 = db.add_custom_role("")
    check("empty string returns False", not ok3)
    ok4 = db.add_custom_role("   ")
    check("whitespace-only returns False", not ok4)
    count_after = len(db.get_custom_roles())
    check("no empty entries added", count_after == 3, str(count_after))

    # --- delete ---
    deleted = db.delete_custom_role("Data Analyst")
    check("delete existing returns True", deleted)
    roles4 = db.get_custom_roles()
    check("deleted role gone", "Data Analyst" not in roles4, str(roles4))
    check("other roles intact", len(roles4) == 2, str(roles4))

    # --- delete case-insensitive ---
    db.add_custom_role("DevOps Engineer")
    deleted2 = db.delete_custom_role("devops engineer")
    check("delete case-insensitive works", deleted2)
    check("role removed after case-insensitive delete",
          "DevOps Engineer" not in db.get_custom_roles())

    # --- delete nonexistent ---
    deleted3 = db.delete_custom_role("Nonexistent Role")
    check("delete nonexistent returns False", not deleted3)

    # --- clean up ---
    with db._get_conn() as (conn, cur):
        cur.execute("DELETE FROM custom_roles")

    print("\n== result:", "ALL CHECKS PASSED" if all(RESULTS) else "SOME CHECKS FAILED")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
