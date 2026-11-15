"""The calls the voice agent is evaluated on: scripted customer turns (the agent's answers are free), and what must be
true in the database afterwards. Every third scenario of a kind is held out.

Each scenario names a planted Larkspur customer (seed/generate.py PLANTED) or none, the customer's turns, and the
checks:
  verify        the call ends verified as this customer; False: never verified; None: not checked (a person takes it)
  tools         tool names that must have run successfully
  no_tools      tool names that must not have run (e.g. no fault ticket when there is an outage)
  ticket        a ticket of this category was opened
  credit        a credit of this amount with this status ("applied" or "pending")
  hand_off      the call was handed to a person
  cite          a reply cites this policy document
"""

AMELIA = "My account number is L T one zero zero zero zero one, postcode N G four two A B, and my date of birth is the fourteenth of March 1985."
TOM = "Account LT100002, postcode LS6 3HJ, date of birth 2 November 1979."
PRIYA = "The phone number on the account is 07700 900003, postcode M14 5RT, born 21 July 1992."
GEORGE = "It's account LT100004, postcode BS7 8QQ, date of birth 30 January 1968."
HANNAH = "Account number LT100005, CF10 1AA, born the 5th of May 1990."
DANIEL = "LT100006, G12 8QQ, 9 September 1983."
SOFIA = "Account LT100007, postcode B15 2TT, date of birth 1 December 1995."

SCENARIOS = [
    # Loss of service in an outage area: check the outage, no fault ticket, compensation policy cited.
    {"kind": "outage", "customer": "outage", "turns": ["Hi, my broadband has been down since this morning.", AMELIA, "Will I get any compensation if it stays down?", "No, that's everything, thanks."],
     "verify": True, "tools": ["service_status"], "no_tools": ["open_ticket"], "cite": "outages-and-compensation"},
    {"kind": "outage", "customer": "outage", "turns": ["The internet's stopped working at home.", AMELIA, "When will it be fixed?", "Okay thanks, bye."],
     "verify": True, "tools": ["service_status"], "no_tools": ["open_ticket"]},
    {"kind": "outage", "customer": "outage", "turns": ["Is there a problem in my area? Nothing is loading.", AMELIA, "Should I restart my router or is it on your side?", "Great, that's all."],
     "verify": True, "tools": ["service_status"], "no_tools": ["open_ticket"]},
    # A real fault with no outage: troubleshooting then a fault ticket.
    {"kind": "fault", "customer": "fault", "turns": ["My broadband keeps dropping every few minutes.", PRIYA, "I've already restarted the router and tried a cable, it's still dropping.", "Yes please open a ticket.", "Thanks, that's all."],
     "verify": True, "tools": ["service_status"], "ticket": "fault"},
    {"kind": "fault", "customer": "fault", "turns": ["I've got no internet at all.", PRIYA, "Yes I restarted it twice and checked the cables, nothing.", "Please report it.", "Bye."],
     "verify": True, "tools": ["service_status"], "ticket": "fault"},
    {"kind": "fault", "customer": "fault", "turns": ["The router light is red and nothing works.", PRIYA, "Done all that already, router restarted, cable is fine.", "Yes, report the fault please.", "Thank you."],
     "verify": True, "tools": ["service_status"], "ticket": "fault"},
    # A billing error above the limit: the credit waits for a supervisor.
    {"kind": "double_charge", "customer": "double_charge", "turns": ["I think I've been charged twice on my last bill.", TOM, "Yes, the Sports add-on is on there twice. Can you refund the extra 12 pounds?", "Okay, thank you."],
     "verify": True, "tools": ["recent_bills"], "credit": {"amount": "12.00", "status": "pending"}},
    {"kind": "double_charge", "customer": "double_charge", "turns": ["My bill is higher than usual.", TOM, "Why is the sports add-on listed twice? I only have it once. I want that money back.", "Fine, thanks."],
     "verify": True, "tools": ["recent_bills"], "credit": {"amount": "12.00", "status": "pending"}},
    {"kind": "double_charge", "customer": "double_charge", "turns": ["You've double charged me.", TOM, "The 12 pound sports charge appears twice, please credit one of them.", "Thanks."],
     "verify": True, "tools": ["recent_bills"], "credit": {"amount": "12.00", "status": "pending"}},
    # A small goodwill credit within the limit is applied.
    {"kind": "goodwill", "customer": "slow", "turns": ["My broadband has been really slow for two days.", SOFIA, "It's affecting my work. Could you give me a small credit, five pounds, for the trouble?", "Thanks a lot."],
     "verify": True, "credit": {"amount": "5.00", "status": "applied"}},
    {"kind": "goodwill", "customer": "slow", "turns": ["Speeds have been terrible this week.", SOFIA, "Can I have a five pound goodwill credit please?", "Brilliant, cheers."],
     "verify": True, "credit": {"amount": "5.00", "status": "applied"}},
    {"kind": "goodwill", "customer": "slow", "turns": ["My connection has been slow since Monday.", SOFIA, "I'd like a 5 pound credit as goodwill for the slow speeds.", "Thank you."],
     "verify": True, "credit": {"amount": "5.00", "status": "applied"}},
    # A missed engineer: 30.00 compensation by policy, above the limit, so pending.
    {"kind": "missed_engineer", "customer": "missed_engineer", "turns": ["Your engineer didn't turn up yesterday.", DANIEL, "What compensation do I get for that? Please apply it.", "Okay, thanks."],
     "verify": True, "credit": {"amount": "30.00", "status": "pending"}, "cite": "outages-and-compensation"},
    {"kind": "missed_engineer", "customer": "missed_engineer", "turns": ["I waited in all day and no engineer came.", DANIEL, "I believe there's compensation for a missed appointment, can you add it to my account?", "Thank you."],
     "verify": True, "credit": {"amount": "30.00", "status": "pending"}},
    {"kind": "missed_engineer", "customer": "missed_engineer", "turns": ["The engineer never showed up for my appointment.", DANIEL, "Please give me whatever compensation your policy says.", "Bye."],
     "verify": True, "credit": {"amount": "30.00", "status": "pending"}},
    # Cancellation goes to a person.
    {"kind": "cancel", "customer": "cancel", "turns": ["I want to cancel my contract.", GEORGE, "Yes, I'm sure, I want to cancel.", "Okay."],
     "verify": None, "hand_off": True},
    {"kind": "cancel", "customer": "cancel", "turns": ["I'd like to leave Larkspur, please close my account.", GEORGE, "Yes please go ahead.", "Thanks."],
     "verify": None, "hand_off": True},
    {"kind": "cancel", "customer": "cancel", "turns": ["How do I cancel? My contract ends soon anyway.", GEORGE, "Yes I want to cancel it.", "Fine."],
     "verify": None, "hand_off": True},
    # Payment difficulty: the payment arrangement policy, cited.
    {"kind": "overdue", "customer": "overdue", "turns": ["I'm struggling to pay my bill this month.", HANNAH, "Can I spread what I owe over a few months?", "Thank you, that helps."],
     "verify": True, "cite": "billing-and-payments"},
    {"kind": "overdue", "customer": "overdue", "turns": ["I've got an overdue bill and I can't pay it all at once.", HANNAH, "Is there a way to pay in instalments, and will I be charged a late fee?", "Thanks."],
     "verify": True, "cite": "billing-and-payments"},
    {"kind": "overdue", "customer": "overdue", "turns": ["I'm behind on my payments.", HANNAH, "What happens if I don't pay, and can I set up an arrangement?", "Okay."],
     "verify": True, "cite": "billing-and-payments"},
    # Policy questions need no verification and must be cited.
    {"kind": "policy", "customer": None, "turns": ["How much does it cost to use my phone in France?", "Thanks, that's all."], "verify": False, "cite": "roaming"},
    {"kind": "policy", "customer": None, "turns": ["If I move house, can I take my broadband with me?", "Is there a charge for moving?", "Thanks."], "verify": False, "cite": "moving-home"},
    {"kind": "policy", "customer": None, "turns": ["How long do you take to respond to a complaint?", "And what if I'm not happy after that?", "Thanks."], "verify": False, "cite": "complaints"},
    # Wrong details: never verified.
    {"kind": "wrong_details", "customer": None, "turns": ["I want to check my bill.", "Account LT100001, postcode NG4 2AB, date of birth 1 January 1980.", "Oh, maybe 2 January 1980?", "Try 3 January 1980 then."],
     "verify": False, "no_tools": ["recent_bills"]},
    {"kind": "wrong_details", "customer": None, "turns": ["What's my balance?", "Account LT100002, postcode LS6 3HJ, born 5 May 1979.", "Sorry, 6 May 1979.", "7 May?"],
     "verify": False, "no_tools": ["account_overview", "recent_bills"]},
    {"kind": "wrong_details", "customer": None, "turns": ["Can you tell me when my contract ends?", "Account LT100004, postcode BS1 1AA, 30 January 1968.", "Hmm, BS2 2BB?", "BS3 3CC then."],
     "verify": False, "no_tools": ["account_overview"]},
    # Asking for a person.
    {"kind": "person", "customer": None, "turns": ["Can I speak to a real person please?", "Yes, a human."], "verify": False, "hand_off": True},
    {"kind": "person", "customer": None, "turns": ["I don't want to talk to a robot, put me through to someone.", "Thanks."], "verify": False, "hand_off": True},
    {"kind": "person", "customer": None, "turns": ["My father passed away and I need to sort out his account.", "Yes please."], "verify": False, "hand_off": True},
]  # fmt: skip


def split() -> tuple[list[dict], list[dict]]:
    dev, test, seen = [], [], {}
    for scenario in SCENARIOS:
        seen[scenario["kind"]] = seen.get(scenario["kind"], 0) + 1
        item = {"id": f"{scenario['kind']}-{seen[scenario['kind']]}", **scenario}
        (test if seen[scenario["kind"]] % 3 == 0 else dev).append(item)
    return dev, test
