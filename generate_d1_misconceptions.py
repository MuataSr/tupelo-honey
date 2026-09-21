#!/usr/bin/env python3
"""Generate 50 college-level FCLE Domain 1 misconceptions via Z.AI API."""

import json
import urllib.request
import ssl
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import misconception_codes  # noqa: E402  real SS.7.CG codes; refuses the "FCLE" placeholder

DOMAIN = 1

def _env_key(name):
    """Read a credential from the environment, falling back to a repo-root .env.
    Credentials are never committed - see .env.example."""
    v = os.environ.get(name, "")
    if not v and os.path.exists(".env"):
        for _line in open(".env"):
            if _line.strip().startswith(name + "="):
                v = _line.split("=", 1)[1].strip().strip("\"'")
                break
    if not v:
        raise SystemExit(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            f"or export {name}."
        )
    return v

API_KEY = _env_key("ZAI_API_KEY")
BASE_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
MODEL = "glm-5.1"
OUTPUT_FILE = "/home/muatasr/.nanobot/workspace/fcle-study-app/data/misconceptions_d1.json"

EXISTING = [
    "Because the textbook says tradeoffs are 'especially common' in Congress, it means Congress always agrees on things and only has to choose the 'best' option.",
    "Lawmakers only vote based on what their political party leaders tell them to do.",
    "Since House members have 2-year terms, they are always more independent and never follow party rules.",
    "The government can just ban all guns immediately to solve the problem of school shootings.",
    "If a law doesn't help my specific district, my representative will ignore it and vote against it.",
    "The textbook example about oil drilling proves that Congress only cares about making money for big companies.",
    "Because state governments have tried to balance gun interests, the federal government can do whatever it wants without needing to balance anything.",
    "When the text says legislators might 'ignore voters' to follow party leaders, it means those voters never have a say in government.",
    "The gun debate is only about whether guns should exist, so the background check laws mentioned aren't really a 'tradeoff'.",
    "If the government tries to resolve conflicting concerns through tradeoffs, it means the conflict is finally solved and everyone is happy.",
    "If the President's party doesn't have 60 votes in the Senate, no laws can ever be passed.",
    "The Senate is a 'super-majority' because the President needs more than half the votes to do anything.",
    "The 'loyal opposition' is the group of people who support the President but disagree with their own party members.",
    "Partisan polarization means parties are too similar and don't offer different ideas.",
    "A 'hold' is a formal vote where senators agree to pass a law immediately.",
    "Divided government is good because it means everyone agrees on everything.",
    "The President can ignore the Senate's 60-vote rule whenever they want to.",
    "Unified government means the President and the Senate are run by the same two people.",
    "If a party is the 'loyal opposition,' they are no longer allowed to run for office again.",
    "Partisan polarization is when parties stop fighting each other and start helping each other all the time.",
    "The media has no real power because the government can just ignore the news and do whatever they want.",
    "Since the newspaper's effect was diminished through conversation, the media today doesn't change what people think anymore.",
    "The First Amendment protects the government from being forced to release secrets, so the media can't ever force the government to speak.",
    "News stories are just facts, so if two different news stations report on the same thing, they should be exactly the same.",
    "The hypodermic theory means the media shoots facts directly into our brains, so we automatically know what is true without thinking.",
    "The media only cares about making money, so they never tell the truth about government problems.",
    "The James Risen case ended when the newspaper won, meaning the government will never stop the media from reporting.",
    "If the media creates a narrative or frame for a story, it is lying to the public about what actually happened.",
    "Because the Supreme Court refused to hear an appeal in the Risen case, the media has no legal protection when the government subpoenas them.",
    "Cultivation theory says the media makes us crazy or confused about the real world.",
    "If a poll asks me the same question as my friend, the results will be exactly the same and prove we think alike.",
    "Straw polls (like those on Facebook) are just as good as real polls because they ask a lot of people quickly.",
    "If a poll predicted the election wrong, like the Literary Digest did, it means politicians don't listen to voters.",
    "Polling is just guessing who will win, so the numbers aren't really facts.",
    "If the poll says 51% of people support something, that means 51% of my specific friends and family agree.",
    "Politicians only look at polls to see what people want, so polls tell politicians how to make laws.",
    "The Literary Digest was bad because they didn't call enough people to get answers.",
    "Since polls have been around for only 80 years, they must be unreliable because they are new.",
    "If I take a quiz on my phone, that counts as a real poll that can be trusted to predict the election.",
    "The difference between liberals and conservatives is just in the polls, not in real life.",
    "If I don't live in a state where my party is losing (like Democrats in Utah), then voting there is a waste of time and I shouldn't bother going to the polls.",
    "Third parties like the Green Party or Libertarian Party can win the presidency if they get enough votes.",
    "The only reason some people don't vote is because they hate their country and want to protest.",
    "Younger people don't vote because they don't care about politics, but actually, they just prefer to volunteer their time instead.",
    "If my party has a clear majority in my state, I will automatically win all the electoral votes no matter what.",
    "Running for governor is super expensive, so only rich people can do it.",
    "Voting is easy because you just need to show up on election day.",
    "The presidential election is always a choice between two bad options, so there's no point in trying to pick a winner.",
    "If I vote for a third party, my vote doesn't count at all because they can't win.",
    "Since the electoral votes go to the person with the most popular votes in a state, I should just stay home and let someone else win.",
    "Voter ID laws are purely about preventing fraud and have no effect on who gets to vote.",
    "Political socialization only happens in school — what you learn in civics class determines your political views.",
    "The presidential candidate who wins the popular vote always becomes president.",
    "Interest groups and lobbyists are basically the same thing as PACs.",
    "The pluralist model of democracy means every group gets equal influence over policy.",
    "The media just reports the news objectively — bias in media is a recent problem caused by social media.",
    "Iron triangles — the alliance between agencies, interest groups, and congressional committees — are illegal because they bypass democratic accountability.",
    "Primary elections and general elections work the same way — any voter can vote for any candidate.",
    "A swing state is a state that changes which party it votes for every single election.",
    "The elite theory of democracy means a small secret group of wealthy people literally controls all government decisions.",
]

DOMAIN_CONTEXT = """Domain 1: American Democracy (FCLE — college level)
Topics: Natural rights philosophy (Locke, Montesquieu), Social contract theory, Limited government and rule of law, Popular sovereignty, Citizen participation (voting, elections), Political parties and interest groups, Public opinion and media, Direct democracy (initiatives, referendums, recalls).

These must be COLLEGE-LEVEL misconceptions — deeper nuance, constitutional philosophy, theoretical understanding. NOT middle school civics.

Output format: JSON array of objects with keys: benchmark_code (a real standard code), misconception (40-120 chars), correction (80-200 chars), difficulty (always "hard"), fcle_domain (always 1).

Every item MUST carry a real standard code. "FCLE" is NOT a code and is rejected.
Choose the ONE standard the misconception is really about, from this list only:
""" + misconception_codes.prompt_block(DOMAIN)

def call_api(prompt, batch_num):
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a civics assessment expert. Return ONLY valid JSON arrays. No markdown, no explanation, no code fences."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 4000
    }).encode()

    req = urllib.request.Request(BASE_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    })

    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        raw = json.loads(resp.read())
        content = raw["choices"][0]["message"]["content"]
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        return json.loads(content)


def main():
    all_misconceptions = []

    # 5 batches of 10 each
    batches = [
        {
            "num": 1,
            "topics": "Natural rights philosophy (Locke, Montesquieu) and Social contract theory",
            "prompt": f"""{DOMAIN_CONTEXT}

For this batch, focus ONLY on: Natural rights philosophy (Locke, Montesquieu) and Social contract theory.

Generate exactly 10 misconceptions. Each misconception should reflect a COLLEGE student's misunderstanding of:
- Locke's natural rights (life, liberty, property) vs. Jefferson's formulation (life, liberty, pursuit of happiness)
- Locke's state of nature as a state of war vs. a state of equality
- The distinction between natural rights and legal rights
- Social contract as actual historical event vs. theoretical framework
- Montesquieu's separation of powers vs. checks and balances
- How Locke influenced the Declaration but NOT the Constitution directly
- The difference between Locke's consent-based government and Hobbes's Leviathan
- Natural law vs. positive law
- Locke's right of revolution and its limits
- Montesquieu's influence on federalism

Do NOT duplicate any of these existing misconceptions (for reference only — different topics):
{json.dumps(EXISTING[:10])}

Return a JSON array of exactly 10 objects."""
        },
        {
            "num": 2,
            "topics": "Limited government, rule of law, popular sovereignty",
            "prompt": f"""{DOMAIN_CONTEXT}

For this batch, focus ONLY on: Limited government and rule of law, and Popular sovereignty.

Generate exactly 10 misconceptions. Each misconception should reflect a COLLEGE student's misunderstanding of:
- Limited government meaning government can do nothing (vs. government constrained by constitution)
- Rule of law meaning no one is above the law vs. rule BY law (authoritarian)
- Judicial review as explicitly stated in the Constitution (it's not — Marbury v. Madison)
- Popular sovereignty meaning direct majority rule on everything
- The tension between popular sovereignty and minority rights
- How federalism complicates popular sovereignty (layered sovereignty)
- Constitutional supremacy vs. parliamentary sovereignty
- The difference between a republic and a democracy at the founding
- How the Bill of Rights limits government, not citizens
- The concept of unenumerated rights and the 9th Amendment

Do NOT duplicate any of these existing misconceptions:
{json.dumps(EXISTING[10:20])}

Return a JSON array of exactly 10 objects."""
        },
        {
            "num": 3,
            "topics": "Citizen participation (voting, elections)",
            "prompt": f"""{DOMAIN_CONTEXT}

For this batch, focus ONLY on: Citizen participation (voting, elections).

Generate exactly 10 misconceptions. Each misconception should reflect a COLLEGE student's misunderstanding of:
- The Electoral College as a direct reflection of popular vote
- Voter suppression vs. voter fraud as the primary threat to elections
- The rational choice model of voting (Downs) and why people vote despite low impact
- Closed vs. open primaries and their effects on candidate selection
- How gerrymandering works (cracking vs. packing) beyond "drawing weird districts"
- The Voting Rights Act of 1965 and Shelby County v. Holder (2013) impact
- Motor Voter laws and automatic voter registration effects
- The role of the 15th, 19th, 24th, and 26th Amendments in expanding suffrage
- Australia's compulsory voting vs. US voluntary voting trade-offs
- The paradox of voting and expressive vs. instrumental voting

Do NOT duplicate any of these existing misconceptions:
{json.dumps(EXISTING[20:30])}

Return a JSON array of exactly 10 objects."""
        },
        {
            "num": 4,
            "topics": "Political parties and interest groups",
            "prompt": f"""{DOMAIN_CONTEXT}

For this batch, focus ONLY on: Political parties and interest groups.

Generate exactly 10 misconceptions. Each misconception should reflect a COLLEGE student's misunderstanding of:
- The US two-party system as constitutionally mandated (it's not — Duverger's Law)
- Party realignments vs. dealignments (critical elections theory)
- The difference between party identification and ideology
- How interest groups use amicus curiae briefs vs. direct lobbying
- The revolving door between government and interest groups
- Buckley v. Valeo and Citizens United — money as speech
- Super PACs vs. traditional PACs contribution rules
-pluralist vs. elite vs. hyperpluralist theories of interest group politics
- The role of political party platforms (are they binding?)
- How interest group pluralism can lead to policy gridlock

Do NOT duplicate any of these existing misconceptions:
{json.dumps(EXISTING[30:40])}

Return a JSON array of exactly 10 objects."""
        },
        {
            "num": 5,
            "topics": "Public opinion, media, direct democracy",
            "prompt": f"""{DOMAIN_CONTEXT}

For this batch, focus ONLY on: Public opinion and media, and Direct democracy (initiatives, referendums, recalls).

Generate exactly 10 misconceptions. Each misconception should reflect a COLLEGE student's misunderstanding of:
- Public opinion as stable vs. fluid and shaped by question wording
- Agenda-setting vs. priming vs. framing (McCombs & Shaw)
- The gatekeeping function of media editors
- Selective exposure and echo chambers in the digital age
- The Fairness Doctrine and its repeal under Reagan
- Direct democracy mechanisms: initiative (citizen-originated) vs. referendum (legislature-originated)
- Recall elections as standard democratic tool vs. extraordinary measure
- Progressive Era origins of direct democracy in US states
- How ballot initiative wording affects outcomes (yes bias)
- The tension between direct democracy and representative democracy

Do NOT duplicate any of these existing misconceptions:
{json.dumps(EXISTING[40:50])}

Return a JSON array of exactly 10 objects."""
        }
    ]

    for batch in batches:
        print(f"\n=== Batch {batch['num']}: {batch['topics']} ===")
        try:
            result = call_api(batch["prompt"], batch["num"])
            print(f"  Got {len(result)} items")
            for item in result:
                # Validate and clean
                item["benchmark_code"] = misconception_codes.validate(
                    item.get("benchmark_code"), domain=DOMAIN)
                item["difficulty"] = "hard"
                item["fcle_domain"] = 1
                mc = item.get("misconception", "")
                corr = item.get("correction", "")
                print(f"  ✓ {mc[:80]}...")
            all_misconceptions.extend(result)
        except Exception as e:
            print(f"  ERROR: {e}")

    # Deduplicate by misconception text
    seen = set()
    unique = []
    for m in all_misconceptions:
        mc = m.get("misconception", "").strip()
        if mc and mc not in seen:
            seen.add(mc)
            unique.append(m)

    # Trim to exactly 50
    final = unique[:50]

    print(f"\n=== SUMMARY ===")
    print(f"Total generated: {len(all_misconceptions)}")
    print(f"After dedup: {len(unique)}")
    print(f"Final (capped at 50): {len(final)}")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(final, f, indent=2)

    print(f"Saved to {OUTPUT_FILE}")

    # Verify
    with open(OUTPUT_FILE) as f:
        data = json.load(f)
    assert len(data) == 50, f"Expected 50, got {len(data)}"
    for i, item in enumerate(data):
        assert "benchmark_code" in item, f"Item {i} missing benchmark_code"
        assert "misconception" in item, f"Item {i} missing misconception"
        assert "correction" in item, f"Item {i} missing correction"
        assert "difficulty" in item, f"Item {i} missing difficulty"
        assert "fcle_domain" in item, f"Item {i} missing fcle_domain"
    print("✅ Verification passed: 50 valid items")

if __name__ == "__main__":
    main()
