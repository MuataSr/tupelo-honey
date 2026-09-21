#!/usr/bin/env python3
"""
Add 50 postsecondary-level FCLE misconceptions to fill identified gaps.
Run: python3 scripts/add_fcle_misconceptions.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "tupelo.db"

MISCONCEPTIONS = [
    # ─── Domain 1: American Democracy (10) ────────────────────────
    (1, "easy",
     "Voter ID laws are purely about preventing fraud and have no effect on who gets to vote.",
     "Voter ID laws have been shown in multiple studies to disproportionately reduce turnout among minority, low-income, and elderly voters. Courts have struck down several as violating the Voting Rights Act or the 14th Amendment's Equal Protection Clause."),

    (1, "medium",
     "Political socialization only happens in school — what you learn in civics class determines your political views.",
     "Political socialization is a lifelong process influenced by family (the strongest predictor of party ID), peers, religion, media, and major life events. School is one factor but rarely the most influential."),

    (1, "easy",
     "The presidential candidate who wins the popular vote always becomes president.",
     "The Electoral College, not the popular vote, determines the president. Five presidents (1824, 1876, 1888, 2000, 2016) won the Electoral College while losing the national popular vote."),

    (1, "medium",
     "Interest groups and lobbyists are basically the same thing as PACs.",
     "Interest groups advocate for policy positions; lobbyists are their hired advocates. PACs (Political Action Committees) are the fundraising arms that collect and donate money to candidates. They are related but legally and functionally distinct entities."),

    (1, "hard",
     "The pluralist model of democracy means every group gets equal influence over policy.",
     "Pluralism holds that competition among many groups prevents any single group from dominating — but it does not guarantee equal influence. Groups with more resources, organization, and access consistently outperform marginalized groups, which is the main critique of pluralist theory."),

    (1, "medium",
     "The media just reports the news objectively — bias in media is a recent problem caused by social media.",
     "Media bias has existed since the earliest American newspapers (Federalist vs. Republican press in the 1790s). Modern bias manifests as selection bias (which stories get covered), framing (how stories are presented), and agenda-setting (which issues seem important). Social media amplified but did not create bias."),

    (1, "hard",
     "Iron triangles — the alliance between agencies, interest groups, and congressional committees — are illegal because they bypass democratic accountability.",
     "Iron triangles are not illegal; they are a widely studied feature of the American political system. They form naturally when agencies need congressional funding, committees need policy expertise, and interest groups need favorable regulations. Critics argue they reduce transparency, but they operate within legal bounds."),

    (1, "medium",
     "Primary elections and general elections work the same way — any voter can vote for any candidate.",
     "Primary elections are run by political parties, not the government, and many states use closed primaries where only registered party members can vote. Open primaries allow any voter, but the rules vary significantly by state."),

    (1, "easy",
     "A swing state is a state that changes which party it votes for every single election.",
     "A swing state (or battleground state) is one where both major parties have similar levels of support, making the outcome unpredictable. It does not need to switch parties every election — it just needs to be competitive enough that campaigns invest resources there."),

    (1, "hard",
     "The elite theory of democracy means a small secret group of wealthy people literally controls all government decisions.",
     "Elite theory (C. Wright Mills, 1956) argues that a small group of military, corporate, and political leaders hold disproportionate influence — not that they control every decision. It is a structural analysis of power concentration, not a conspiracy theory about secret control."),

    # ─── Domain 2: US Constitution (10) ──────────────────────────
    (2, "medium",
     "The Commerce Clause only applies to trade between states — it has nothing to do with activities within a single state.",
     "Under the Commerce Clause, Congress has regulated intrastate activities that substantially affect interstate commerce (Wickard v. Filburn, 1942). Growing wheat for personal consumption was regulated because it reduced demand in the national market."),

    (2, "hard",
     "The Necessary and Proper Clause is a loophole that lets Congress pass any law it wants.",
     "The Necessary and Proper Clause (Article I, Section 8) only authorizes laws that are genuinely useful for executing Congress's enumerated powers. In McCulloch v. Maryland (1819), Chief Justice Marshall established that 'necessary' means convenient or useful — not absolutely indispensable — but the law must still tie to a listed power."),

    (2, "medium",
     "The Supremacy Clause means federal law always automatically overrides state law in every situation.",
     "While federal law is supreme under the Constitution, Congress can only preempt state law within its enumerated powers. States retain police powers (health, safety, morals) that the federal government cannot override unless acting within a valid constitutional grant of authority."),

    (2, "easy",
     "Only Congress can propose amendments to the Constitution.",
     "Two-thirds of state legislatures can call a constitutional convention to propose amendments (Article V). This method has never been used, but 27 states have called for a convention at various points in history. Congress retains the sole power to choose the ratification method."),

    (2, "medium",
     "The 10th Amendment gives states all powers not listed in the Constitution, which means states can ignore federal laws they disagree with.",
     "The 10th Amendment reserves powers to the states or the people, but the Supremacy Clause makes valid federal law supreme over conflicting state law. Nullification — a state declaring a federal law void — has been rejected repeatedly (Nullification Crisis 1832, Cooper v. Aaron 1958)."),

    (2, "medium",
     "A pocket veto is when the president vetoes a bill by putting it in their pocket and never signing it.",
     "A pocket veto is specific: if Congress adjourns within 10 days of sending a bill to the president and the president does not sign it, the bill dies without a veto override opportunity. If Congress is still in session, not signing within 10 days makes the bill law automatically."),

    (2, "hard",
     "Executive privilege means the president can keep any information secret from Congress or the courts at any time.",
     "Executive privilege is not absolute. In United States v. Nixon (1974), the Supreme Court ruled that privilege cannot be used to withhold evidence relevant to a criminal prosecution. The privilege is a qualified right that must yield to other constitutional interests."),

    (2, "medium",
     "The War Powers Resolution gives presidents 60 days to use military force, after which Congress must declare war.",
     "The War Powers Resolution (1973) requires the president to notify Congress within 48 hours of deploying troops and withdraw after 60 days (plus 30-day withdrawal period) without congressional authorization. It does not require a formal declaration of war — an authorization of military force (AUMF) is sufficient."),

    (2, "easy",
     "Impeachment means the president is removed from office immediately after the House votes to impeach.",
     "Impeachment is only the House's charge (like an indictment). The Senate then holds a trial, and conviction requires a two-thirds vote. Andrew Johnson and Bill Clinton were impeached but not convicted; Nixon resigned before the full House could vote."),

    (2, "hard",
     "The elastic clause and the supremacy clause are basically the same thing — both expand federal power over states.",
     "They are distinct constitutional provisions. The Necessary and Proper Clause (elastic clause, Article I §8) authorizes Congress to pass laws needed to execute its powers. The Supremacy Clause (Article VI) establishes that valid federal law overrides conflicting state law. They work together but address different questions: what can Congress do, and who wins when laws conflict."),

    # ─── Domain 3: Founding Documents (15) ───────────────────────
    (3, "medium",
     "Federalist No. 10 says factions can be eliminated if we just have good leaders who put the country first.",
     "Madison argued the opposite — factions cannot be eliminated without destroying liberty itself. Instead, he proposed controlling their effects through a large republic where no single faction could become a majority, and by having so many factions that they would check each other."),

    (3, "hard",
     "Federalist No. 10 supports direct democracy as the best way to prevent the tyranny of the majority.",
     "Federalist No. 10 actually argues against pure democracy, which Madison called 'a specter of short duration.' He favored a large republic with representative government (republic) because it would filter public opinion through elected officials and dilute factional power across a large population."),

    (3, "medium",
     "Federalist No. 51 says separation of powers works because government officials are naturally virtuous and respect the system.",
     "Federalist No. 51 argues the opposite — 'ambition must be made to counteract ambition.' Madison believed human nature required institutional checks, not personal virtue. Each branch would jealously guard its own power, which would naturally limit the others."),

    (3, "hard",
     "The 'double security' Madison describes in Federalist No. 51 means having two houses of Congress as a check on the president.",
     "Double security refers to federalism (divided power between federal and state governments) combined with separation of powers (three branches checking each other). The federal structure provides one layer of protection for rights, and the internal checks provide another."),

    (3, "medium",
     "The Anti-Federalists lost the debate over ratification because they didn't have any good arguments — they just complained about everything.",
     "Anti-Federalists raised legitimate concerns: the lack of a Bill of Rights, the potential for executive tyranny, the risk of federal overreach, and the loss of state sovereignty. Their pressure directly led to the Bill of Rights as the first 10 amendments. Many of their warnings about consolidated power remain relevant in constitutional debates."),

    (3, "hard",
     "Brutus and the Anti-Federalists opposed the Constitution mainly because they wanted stronger state governments to have more power than the federal government.",
     "Brutus (likely Robert Yates) argued that a large republic would be unresponsive to citizens and that the Necessary and Proper Clause and Supremacy Clause would effectively eliminate state sovereignty. The concern was not about states wanting more power per se, but about preserving self-government and preventing distant, unaccountable rulers — the same grievance that motivated the Revolution."),

    (3, "medium",
     "The Declaration of Independence created the American government and established our laws.",
     "The Declaration of Independence is a philosophical and political statement explaining why the colonies were separating from Britain. It created no government and established no laws. The actual framework of government came from the Articles of Confederation (1781) and then the Constitution (1789)."),

    (3, "medium",
     "The Declaration of Independence's list of grievances against King George III is just historical venting — it has no legal significance.",
     "The grievances served as the legal and philosophical justification for independence, demonstrating that the king had violated the social contract. They also influenced the Bill of Rights — protections against quartering soldiers, trial without jury, and taxation without representation all trace to specific grievances listed."),

    (3, "hard",
     "The Declaration of Independence invented the idea of natural rights — Locke's philosophy was not well known before 1776.",
     "John Locke's 'Two Treatises of Government' (1689) was widely read by the Founders. Locke argued that life, liberty, and property were natural rights preceding government. Jefferson adapted this to 'life, liberty, and the pursuit of happiness,' broadening Locke's property focus to a more expansive vision of human flourishing."),

    (3, "easy",
     "The Articles of Confederation were basically the same as the Constitution, just an earlier draft.",
     "The Articles created a weak central government with no executive branch, no national judiciary, no power to tax, no power to regulate commerce, and no standing army. Each state had one vote regardless of population, and amendments required unanimous consent. Shays' Rebellion (1786-87) exposed these weaknesses and drove the Constitutional Convention."),

    (3, "medium",
     "The Articles of Confederation failed because the states were too small and didn't care about working together.",
     "The Articles failed because the structural design made cooperation nearly impossible. Without power to tax, the national government couldn't pay debts or fund an army. Without commerce regulation, states engaged in trade wars. Without an executive, there was no one to enforce laws. The problem was institutional design, not state size or attitude."),

    (3, "hard",
     "The Constitution was ratified quickly once everyone saw how bad the Articles of Confederation were.",
     "Ratification took nearly three years (1787-1790) and was fiercely contested. Rhode Island didn't ratify until 1790, and only after the federal government threatened trade sanctions. Massachusetts ratified by a narrow margin (187-168) only after Federalists promised to add a Bill of Rights."),

    (3, "medium",
     "Federalist No. 10 and Federalist No. 51 say basically the same thing — they're redundant.",
     "Federalist No. 10 addresses the problem of factions and argues a large republic controls them. Federalist No. 51 addresses how to structure government so branches check each other. No. 10 is about the size and composition of the polity; No. 51 is about internal institutional design. They solve different problems."),

    (3, "easy",
     "The Constitution was signed by all the Founding Fathers, so they all agreed on everything in it.",
     "Of the 55 delegates at the Constitutional Convention, only 39 signed. Notable absent signatures included George Mason (refused because it lacked a Bill of Rights), Edmund Randolph (wanted more changes), and Elbridge Gerry (feared consolidated power). Three delegates refused to sign entirely."),

    (3, "hard",
     "The Three-Fifths Compromise in the Constitution proves the Founders believed enslaved people were three-fifths of a person.",
     "The Three-Fifths Compromise was a political agreement about representation and taxation, not a statement about human worth. Southern states wanted enslaved people counted fully for representation but not for taxation; Northern states wanted the opposite. The compromise applied only to apportionment — enslaved people were legally counted as zero for all other purposes."),

    # ─── Domain 4: Landmark Impact (15) ───────────────────────────
    (4, "medium",
     "The Bill of Rights always applied to state governments from the very beginning.",
     "The Bill of Rights originally restricted only the federal government (Barron v. Baltimore, 1833). Through the 14th Amendment's Due Process Clause, the Supreme Court gradually 'incorporated' most protections to apply to the states — a process called the incorporation doctrine that took over a century."),

    (4, "hard",
     "Selective incorporation means the Supreme Court picked and chose which rights to protect based on personal preference.",
     "Selective incorporation means the Court applied Bill of Rights protections to the states case by case, requiring that each right be 'fundamental to the American scheme of justice' (Palko v. Connecticut, 1937). Nearly all protections have been incorporated except the 3rd Amendment, the grand jury requirement (5th), and the 7th Amendment right to jury in civil cases."),

    (4, "medium",
     "Mapp v. Ohio just said police need a warrant to search your house — which was already the rule.",
     "Before Mapp (1961), the exclusionary rule (evidence obtained illegally cannot be used in court) applied only to federal cases (Weeks v. United States, 1914). Mapp extended the exclusionary rule to all states through the 14th Amendment, fundamentally changing how state police conduct searches."),

    (4, "easy",
     "If you can't afford a lawyer, you just have to represent yourself in court.",
     "Gideon v. Wainwright (1963) established that the 6th Amendment's right to counsel applies to all felony cases in state courts. The state must provide an attorney for defendants who cannot afford one. This ruling led to the creation of public defender systems nationwide."),

    (4, "easy",
     "Miranda rights are just a formality — police have to read them but it doesn't really matter if they don't.",
     "Miranda v. Arizona (1966) established that any statements made during custodial interrogation are inadmissible unless the suspect was informed of their rights (to remain silent, to an attorney, that anything said can be used against them). Failure to read Miranda rights can result in key evidence being excluded from trial."),

    (4, "medium",
     "Tinker v. Des Moines said students have the same free speech rights as adults everywhere.",
     "Tinker (1969) established that students do not 'shed their constitutional rights at the schoolhouse gate,' but it only protected passive symbolic speech (black armbands). The Court also said speech could be restricted if it substantially disrupted school operations. Later cases (Bethel, Fraser, Morse) significantly limited student speech rights."),

    (4, "medium",
     "Engel v. Vitale banned all prayer in public schools — students aren't even allowed to pray silently.",
     "Engel v. Vitale (1962) banned state-composed, mandatory school prayer. It did not prohibit individual, voluntary prayer by students. Students may pray silently, read religious texts during free time, and form religious clubs under the Equal Access Act (1984). The ruling only prevents the school from organizing or leading prayer."),

    (4, "hard",
     "McCulloch v. Maryland is just about a bank — it's not that important for understanding federal power.",
     "McCulloch v. Maryland (1819) established two foundational principles of American constitutional law: (1) Congress has implied powers under the Necessary and Proper Clause to create a national bank, and (2) states cannot tax federal instruments because 'the power to tax is the power to destroy.' It is arguably the most important case on federalism."),

    (4, "medium",
     "Schenck v. United States created the 'clear and present danger' test, which means any speech that's dangerous can be banned.",
     "Schenck (1973, actually 1919) created the test but Justice Holmes wrote that 'the question in every case is whether the words used are of such a nature as to create a clear and present danger that they will bring about the substantive evils that Congress has a right to prevent.' The standard has been narrowed significantly — Brandenburg v. Ohio (1969) replaced it with 'imminent lawless action.'"),

    (4, "hard",
     "Citizens United v. FEC means corporations can donate unlimited money directly to political candidates.",
     "Citizens United (2010) ruled that corporations and unions can spend unlimited money on independent political communications (advertising, documentaries), not direct contributions to candidates. The distinction between independent expenditures and direct contributions remains — direct donations to candidates are still capped under BCRA."),

    (4, "medium",
     "The Civil Rights Act of 1964 was passed because President Johnson just decided to sign it — it was his idea.",
     "The Civil Rights Act resulted from decades of activism — the Montgomery Bus Boycott, sit-ins, Freedom Rides, the March on Washington, and violent backlash against peaceful protesters. Kennedy proposed it in June 1963, and after his assassination, Johnson used his legislative experience and the emotional momentum to overcome a 54-day Senate filibuster by Southern Democrats."),

    (4, "medium",
     "The Voting Rights Act of 1965 wasn't really necessary because the 15th Amendment already guaranteed voting rights.",
     "Despite the 15th Amendment (1870), Southern states used literacy tests, poll taxes, grandfather clauses, and outright violence to disenfranchise Black voters for nearly a century. The VRA of 1965 gave the federal government enforcement power, banned literacy tests, and required federal approval (preclearance) for changes to voting laws in covered jurisdictions."),

    (4, "easy",
     "The Americans with Disabilities Act just means buildings need wheelchair ramps.",
     "The ADA (1990) is comprehensive civil rights legislation modeled on the Civil Rights Act of 1964. It covers employment (employers with 15+ workers), public services, public accommodations, and telecommunications. It prohibits discrimination based on disability and requires reasonable accommodations in all these areas."),

    (4, "hard",
     "Brown v. Board of Education immediately ended segregation in all American schools.",
     "Brown (1954) declared segregated schools unconstitutional, but compliance was not immediate. In Brown II (1955), the Court ruled desegregation should proceed 'with all deliberate speed' — a vague standard Southern states exploited. By 1964, ten years after Brown, less than 2% of Black students in the Deep South attended integrated schools. It took the Civil Rights Act of 1964 to link federal funding to compliance."),

    (4, "medium",
     "Marbury v. Madison established judicial review, which is explicitly written in the Constitution.",
     "Judicial review — the power of courts to declare laws unconstitutional — is not explicitly stated anywhere in the Constitution. Chief Justice Marshall derived it from Article III and the Supremacy Clause in Marbury v. Madison (1803). It became one of the most significant judicial doctrines in American history despite having no explicit textual basis."),
]

def main():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Get current max id
    c.execute("SELECT MAX(id) FROM misconceptions")
    max_id = c.fetchone()[0] or 0

    # Get current counts per domain
    c.execute("SELECT fcle_domain, COUNT(*) FROM misconceptions GROUP BY fcle_domain ORDER BY fcle_domain")
    before = {r[0]: r[1] for r in c.fetchall()}
    before_total = sum(before.values())

    # Insert
    sql = """INSERT INTO misconceptions 
              (benchmark_code, difficulty, misconception, correction, fcle_domain) 
             VALUES (?, ?, ?, ?, ?)"""
    inserted = 0
    for domain, difficulty, misconception, correction in MISCONCEPTIONS:
        c.execute(sql, ("FCLE", difficulty, misconception, correction, domain))
        inserted += 1

    conn.commit()

    # Verify
    c.execute("SELECT fcle_domain, COUNT(*) FROM misconceptions GROUP BY fcle_domain ORDER BY fcle_domain")
    after = {r[0]: r[1] for r in c.fetchall()}
    after_total = sum(after.values())

    print(f"✅ Inserted {inserted} postsecondary-level misconceptions")
    print(f"   Before: {before_total} total → After: {after_total} total (+{after_total - before_total})\n")
    print("Per-domain breakdown:")
    for d in sorted(before.keys()):
        diff = after.get(d, 0) - before.get(d, 0)
        print(f"  Domain {d}: {before.get(d, 0)} → {after.get(d, 0)} (+{diff})")

    # Sample verification
    print("\n=== Sample from each domain ===")
    for d in [1, 2, 3, 4]:
        c.execute("SELECT misconception FROM misconceptions WHERE fcle_domain = ? ORDER BY id DESC LIMIT 1", (d,))
        row = c.fetchone()
        print(f"  D{d}: {row[0][:80]}...")

    conn.close()


if __name__ == "__main__":
    main()
