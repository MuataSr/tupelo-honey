import sqlite3
import json

db = sqlite3.connect('data/fcle.db')
cur = db.cursor()

# Question 1465: USA PATRIOT Act constitutional justification
# Correct: Implied powers
# Wrong[0]: "Enumerated powers"
# Wrong[1]: "Necessary and proper clause"
# Wrong[2]: "Tenth Amendment reservation of powers"
explanations_1465 = [
    "Enumerated powers are those explicitly listed in the Constitution, such as the power to coin money or regulate commerce. Digital surveillance is not explicitly listed among them, so enumerated powers cannot serve as the primary justification for the PATRIOT Act. The correct answer is implied powers, which allow the federal government to exercise authority not explicitly stated but reasonably inferred from its enumerated powers.",
    "While the Necessary and Proper Clause (Article I, Section 8) is the constitutional mechanism that generates implied powers, it is not itself a category of governmental power. The question asks for the type of power that justifies the PATRIOT Act, and the correct answer is implied powers — the broader category that the Necessary and Proper Clause helps create.",
    "The Tenth Amendment reserves powers not delegated to the federal government to the states or the people, which would actually limit federal surveillance authority rather than justify it. The correct answer is implied powers, which operate in the opposite direction by allowing the federal government to exercise powers that are not explicitly listed but are necessary to carry out its enumerated responsibilities."
]

# Question 1557: Shays' Rebellion - why national government couldn't help
# Correct: Articles of Confederation granted no power to levy taxes or maintain standing army
# Wrong[0]: "Federalists argued standing army leads to tyranny"
# Wrong[1]: "President Washington refused the request"
# Wrong[2]: "Continental Congress lacked authority to declare war on Massachusetts"
explanations_1557 = [
    "It was the Anti-Federalists, not the Federalists, who feared that a standing army could lead to tyranny. The Federalists generally supported a stronger national government with military capacity. The correct answer is that the Articles of Confederation simply gave the national government no power to levy taxes or maintain a standing army, making military assistance structurally impossible regardless of any faction's political views.",
    "There was no president under the Articles of Confederation in 1786, as that framework lacked an executive branch entirely. George Washington did not become president until 1789 under the new Constitution. The correct answer is that the Articles of Confederation provided no mechanism for federal military intervention because the national government could not tax or maintain a standing army.",
    "The inability to respond to Shays' Rebellion was not about a lack of authority to declare war on a state. The fundamental problem was structural: under the Articles of Confederation, the national government had no power to levy taxes or maintain a standing army, so it simply could not raise or fund troops to assist Massachusetts in suppressing the rebellion."
]

# Question 1575: Federalist No. 78 - judicial branch characterization
# Correct: Least dangerous branch - no influence over sword or purse
# Wrong[0]: "Most dangerous because power derived directly from the people"
# Wrong[1]: "Primary check with authority to veto legislation and command military"
# Wrong[2]: "Most dangerous because final interpretive power"
explanations_1575 = [
    "Federalist No. 78, written by Alexander Hamilton, argues the exact opposite — that the judiciary is the least dangerous branch, not the most. Additionally, federal judges are appointed for life rather than elected, so their power is not 'derived directly from the people.' Hamilton's key argument is that the judiciary has neither the sword (executive power) nor the purse (legislative power), making it the weakest branch.",
    "The power to veto legislation belongs to the president, and command of the military is an executive function — neither is held by the judicial branch. Federalist No. 78 specifically notes that the judiciary lacks control over both the sword and the purse, which is precisely why Hamilton characterized it as the least dangerous branch rather than the primary checking branch.",
    "While the judiciary does exercise judicial review and interpretive power, Federalist No. 78 explicitly argues that the judicial branch is the least dangerous, not the most. Hamilton reasoned that because the courts can neither enforce their own judgments (lacking the sword) nor fund their operations independently (lacking the purse), they must remain dependent on the other branches, making them the weakest of the three."
]

updates = {
    1465: explanations_1465,
    1557: explanations_1557,
    1575: explanations_1575,
}

for qid, explanations in updates.items():
    we_json = json.dumps(explanations)
    cur.execute('UPDATE questions SET wrong_explanations = ? WHERE id = ?', (we_json, qid))
    print(f"Updated ID {qid}: {cur.rowcount} row(s) affected")

db.commit()

# === VERIFICATION ===
print("\n=== VERIFICATION ===")
all_ok = True
for qid in updates:
    row = cur.execute('SELECT id, question, wrong_answers, wrong_explanations FROM questions WHERE id = ?', (qid,)).fetchone()
    if row is None:
        print(f"ID {qid}: NOT FOUND IN DATABASE!")
        all_ok = False
        continue
    db_id, question, wa_raw, we_raw = row
    wa = json.loads(wa_raw)
    we = json.loads(we_raw)
    print(f"\nID {qid} (db_id={db_id}):")
    print(f"  Question: {question[:90]}...")
    print(f"  wrong_answers count: {len(wa)}")
    print(f"  wrong_explanations count: {len(we)}")
    if len(wa) != len(we):
        print(f"  ✗ MISMATCH: {len(wa)} answers vs {len(we)} explanations!")
        all_ok = False
    for i in range(len(wa)):
        print(f"  Wrong[{i}]: {wa[i][:80]}...")
        print(f"    Expln[{i}]: {we[i][:120]}...")
        # Check the explanation references relevant concepts
        expl_lower = we[i].lower()
        if 'correct answer' in expl_lower or 'correct' in expl_lower:
            print(f"    ✓ References correct answer/concept")
        else:
            print(f"    ✗ Does NOT reference correct answer/concept")
            all_ok = False
    print(f"  ✓ Counts match")

if all_ok:
    print("\n✓ ALL UPDATES VERIFIED SUCCESSFULLY")
else:
    print("\n✗ SOME VERIFICATIONS FAILED")

db.close()
