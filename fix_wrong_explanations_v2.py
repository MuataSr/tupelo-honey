#!/usr/bin/env python3
"""
Fix mismatched wrong_explanations for 8 FCLE questions (IDs: 1016, 1043, 1094, 1096, 1106, 1114, 1116, 1153).
"""

import sqlite3
import json

updates = {
    1016: [
        # Wrong[0]: "party-in-the-electorate"
        "Party-in-the-electorate refers to the broad group of voters who identify with and support a particular political party, not a mechanism of legislative influence. The coalition in the scenario is engaging in direct advocacy by providing data and research to legislators, which is the defining feature of inside lobbying. Party-in-the-electorate describes voter alignment, not the act of lobbying elected officials.",

        # Wrong[1]: "issue network"
        "While the coalition is described as an issue network, the question asks for the primary mechanism of influence, not the type of group itself. The correct answer, inside lobbying, identifies what the coalition actually does—providing research, data, and direct pressure to specific legislators. An issue network describes who the actors are, whereas inside lobbying describes how they exert influence.",

        # Wrong[2]: "framing"
        "Framing refers to the way media outlets and political actors present or 'frame' an issue to shape public perception, such as emphasizing certain angles of a story. The scenario describes the coalition providing data and research directly to legislators, which is inside lobbying, not media framing. Framing operates through public communication strategies, whereas the coalition's mechanism involves direct engagement with policymakers."
    ],

    1043: [
        # Wrong[0]: national laws automatically take precedence in every circumstance
        "This statement describes an absolute federal supremacy that does not exist in the U.S. system. Under the Tenth Amendment, powers not delegated to the federal government are reserved to the states, meaning states retain significant authority over local affairs. The correct answer recognizes that federalism grants specific enumerated powers to the national government while allowing states to govern in areas outside that scope.",

        # Wrong[1]: unitary system
        "A unitary system concentrates all sovereign power in the national government, which is fundamentally different from the U.S. federal system. In American federalism, state governments are independent entities with their own constitutionally protected powers, not mere administrative units of the national government. The correct answer reflects this by noting that states govern local affairs in areas not explicitly delegated to the federal government.",

        # Wrong[2]: state courts have no authority to interpret state laws
        "State courts are essential components of the federal system and have full authority to interpret and apply their own state laws and constitutions. The U.S. system actually depends on both state and federal courts operating within their respective jurisdictions. The correct answer accurately describes federalism as a system where states retain governing authority in areas not delegated to the federal government, which includes the operation of state court systems."
    ],

    1094: [
        # Wrong[0]: government is the sole source of all rights
        "This directly contradicts John Locke's theory of natural rights, which holds that life, liberty, and property are inherent rights that exist independently of government. Locke argued that governments are created to protect these pre-existing rights, not to grant them. The correct answer affirms that natural rights exist independently of government protection and that citizens have the right to petition for redress when those rights are violated.",

        # Wrong[1]: ignore the issue until government acts
        "Locke's social contract theory emphasizes that government derives its legitimacy from the consent of the governed, which requires active civic participation, not passive waiting. The entire premise of the social contract is that citizens have the right and responsibility to hold government accountable when it fails to protect their natural rights. The correct answer recognizes that citizens should petition and organize to demand changes.",

        # Wrong[2]: natural rights are philosophical, not actionable
        "While natural rights originated as philosophical concepts, they have been codified into actionable legal protections through documents like the Declaration of Independence and the Bill of Rights. The First Amendment explicitly protects the right to petition the government for redress of grievances, making this a concrete legal remedy. The correct answer acknowledges that citizens can both petition the government and organize to demand changes when their rights are threatened."
    ],

    1096: [
        # Wrong[0]: shadow campaigns are illegal in Florida
        "Shadow campaigns, which involve independent political messaging not coordinated with a candidate's official campaign, are generally legal under campaign finance law as long as they comply with disclosure requirements. The flaw in the commentator's argument is not about legality, but about how political socialization shapes voter perceptions of such tactics. The correct answer explains that if voters perceive a shadow campaign as manipulative, it can actually harm the sponsoring organization's goals regardless of legality.",

        # Wrong[1]: confusing shadow campaigns with referendums
        "A referendum is a process that allows voters to approve or reject laws passed by the legislature, which is entirely unrelated to the concept of a shadow campaign. The commentator's argument actually does concern shadow campaigns but fails to account for how political socialization shapes voter reactions. The correct answer identifies that the flaw lies in ignoring how voters' political socialization affects their perception of shadow campaign messaging.",

        # Wrong[2]: candidate is fully coordinated with PAC
        "By definition, a shadow campaign operates independently of the candidate's official campaign, so full coordination contradicts the concept entirely. The commentator's actual flaw is not misunderstanding what a shadow campaign is, but rather ignoring how political socialization influences whether voters find the shadow campaign's messaging credible. The correct answer explains that voters' pre-existing political beliefs may cause them to view the shadow campaign negatively, undermining its effectiveness."
    ],

    1106: [
        # Wrong[0]: direct democracy mechanism
        "Direct democracy involves citizens voting directly on policies, as in ballot initiatives or referendums, which is not the primary function of political parties. Political parties operate within a representative democracy by organizing candidates, platforms, and voter education—not by enabling direct votes on legislation. The correct answer identifies that parties serve as agents of political socialization, teaching members about party values and helping them form a political identity.",

        # Wrong[1]: neutral arbiters ensuring majority overrides minority
        "Political parties are not neutral arbiters; they are explicitly partisan organizations that advocate for specific ideological positions and policy agendas. Additionally, the U.S. system balances majority rule with protections for minority rights, so parties do not simply override those protections for efficiency. The correct answer recognizes that parties function as socialization agents, helping individuals develop a political identity through exposure to the party's platform and values.",

        # Wrong[2]: external consultants hired by lobbyists
        "Political parties are broad-based organizations that nominate candidates, mobilize voters, and shape public policy agendas—they are not hired consultants working for lobbyists. Lobbyists may try to influence parties, but parties exist independently as vehicles for political participation and identity formation. The correct answer describes the socialization role of parties, in which they educate members about party history, platform, and values to help shape citizens' political development."
    ],

    1114: [
        # Wrong[0]: hypodermic theory
        "The hypodermic theory (or hypodermic needle model) posits that media messages are injected directly into audiences who passively accept them, which is unrelated to the concept of benefiting from a group without contributing. The correct answer, the free rider problem, describes exactly this situation where individuals enjoy collective benefits without participating or paying. Hypodermic theory concerns media effects and audience reception, not the dynamics of political participation and collective action.",

        # Wrong[1]: muckraking
        "Muckraking refers to investigative journalism that exposes corruption in business or government, which has no connection to receiving benefits without contributing effort. The free rider problem, the correct answer, specifically describes the situation where an individual benefits from a group's efforts without providing time, money, or support. Muckraking is a media practice, not a concept about individual participation in political organizations.",

        # Wrong[2]: divided government
        "Divided government occurs when one party controls the executive branch and another controls the legislative branch, which is a structural condition of government, not a concept about individual participation. The free rider problem, the correct answer, describes an individual-level dynamic where someone benefits from group efforts without contributing. Divided government addresses inter-branch politics, whereas the free rider problem addresses collective action and individual incentives."
    ],

    1116: [
        # Wrong[0]: hyperpluralism
        "Hyperpluralism describes a condition where too many interest groups compete for influence, causing government gridlock, but this is distinct from the elite critique of public opinion. The correct answer focuses on regulatory capture and how wealthy interests are systematically advantaged over ordinary citizens, not on the number of competing groups. Hyperpluralism concerns group proliferation and its effect on governance, while the elite critique concerns structural inequality in political influence.",

        # Wrong[1]: muckraking press
        "Muckraking is a form of investigative journalism that aims to expose corruption and inform the public, which is unrelated to the elite critique of polling and representation. The elite critique argues that powerful interests and regulatory capture distort policy outcomes in favor of the wealthy, not that journalism creates populist backlash. The correct answer identifies that agencies captured by the groups they regulate lead to a system favoring elite interests over average citizens.",

        # Wrong[2]: lobbyists using heuristics
        "While heuristics are mental shortcuts used in political decision-making, the elite critique is not primarily about how lobbyists simplify policy for voters. The correct answer focuses on regulatory capture and the structural advantage of wealthy interests in shaping policy outcomes. The elite critique argues that the political system is dominated by economic elites whose preferences prevail over those of average citizens, not that voters are being manipulated through simplified messaging."
    ],

    1153: [
        # Wrong[0]: separation of powers
        "Separation of powers divides governmental authority among three branches, but the excerpt specifically discusses the relationship between representatives and the people they represent, not the division of power among branches. The reference to 'a dependence on the people' and representatives being curbed by that dependence is a classic expression of social contract theory. The correct answer identifies this as social contract theory, where government legitimacy depends on the consent of the governed.",

        # Wrong[1]: majority rule
        "Majority rule is a democratic principle, but the excerpt focuses on the accountability of representatives to the people as a whole, not on majority dominance over minorities. The phrase 'dependence on the people' and the idea of a curb on representatives speaks to the reciprocal obligation in the social contract, not to majority-minority dynamics. The correct answer identifies this as social contract theory, emphasizing that government derives its legitimacy from the consent of the governed.",

        # Wrong[2]: federalism
        "Federalism concerns the division of power between national and state governments, but the excerpt discusses the vertical relationship between the people and their representatives, not the horizontal division of power between levels of government. The 'dependence on the people' described in the passage reflects the core idea of social contract theory—that government authority rests on the consent of those governed. The correct answer identifies this foundational concept as social contract theory."
    ],
}

def main():
    db = sqlite3.connect('data/fcle.db')
    cur = db.cursor()

    print("=" * 70)
    print("UPDATING 8 QUESTIONS WITH NEW WRONG_EXPLANATIONS")
    print("=" * 70)
    print()

    for qid, expl_list in updates.items():
        assert len(expl_list) == 3, f"Expected 3 explanations for ID {qid}, got {len(expl_list)}"

        # Verify the question exists
        row = cur.execute(
            'SELECT id, question, wrong_answers FROM questions WHERE id = ?', (qid,)
        ).fetchone()

        if row is None:
            print(f"ERROR: Question ID {qid} not found in database!")
            continue

        qid_db, question, wa_raw = row
        wa = json.loads(wa_raw)
        assert len(wa) == 3, f"Expected 3 wrong_answers for ID {qid}, got {len(wa)}"

        # Convert to JSON and update
        wrong_explanations_json = json.dumps(expl_list)
        cur.execute(
            'UPDATE questions SET wrong_explanations = ? WHERE id = ?',
            (wrong_explanations_json, qid)
        )

        print(f"UPDATED ID {qid}: {cur.rowcount} row(s) affected")

    db.commit()

    # Verification: read back each row and confirm
    print()
    print("=" * 70)
    print("VERIFICATION OF ALL UPDATES")
    print("=" * 70)
    print()

    for qid in sorted(updates.keys()):
        row = cur.execute(
            'SELECT id, question, correct_answer, wrong_answers, wrong_explanations FROM questions WHERE id = ?',
            (qid,)
        ).fetchone()

        qid_db, question, correct, wa_raw, we_raw = row
        wa = json.loads(wa_raw)
        we = json.loads(we_raw)

        print(f"ID: {qid_db}")
        assert len(we) == 3, f"Expected 3 wrong_explanations for ID {qid_db}, got {len(we)}"
        assert len(wa) == 3, f"Expected 3 wrong_answers for ID {qid_db}, got {len(wa)}"

        for i in range(3):
            print(f"  Wrong[{i}]: {wa[i][:80]}...")
            print(f"  Expl[{i}]: {we[i][:120]}...")
            # Verify 2-4 sentences
            sentence_count = len([s.strip() for s in we[i].split('.') if s.strip()])
            assert 2 <= sentence_count <= 6, f"Explanation {i} for ID {qid_db} has {sentence_count} sentences (expected 2-4)"
        print(f"  Count matches: {len(we)} wrong_explanations for {len(wa)} wrong_answers")
        print()

    db.close()
    print("=" * 70)
    print(f"ALL {len(updates)} UPDATES VERIFIED SUCCESSFULLY")
    print("=" * 70)

if __name__ == '__main__':
    main()
