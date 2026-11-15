"""The demo organisations' policies. Each document is markdown; every `## n. Heading` starts a citable section.

Written for the demo; the figures (compensation, time limits) are the demo's own and are what the evaluation
checks answers against.
"""

LARKSPUR = {
    "identity-and-privacy": (
        "Identity checks and privacy",
        """
## 1. Before discussing an account
We confirm who we are speaking to before discussing any account details. The caller gives the account number or
the phone number on the account, and then the postcode and the date of birth of the account holder. All three must
match. We never read out a date of birth, a full phone number or a full postcode to a caller.

## 2. Failed checks
After three failed attempts on one call we stop the check and offer to send a one-time code to the email address
on the account, or ask the caller to call back with their details. We do not give hints about which detail was wrong.

## 3. Third parties
We only discuss an account with the account holder or a person they have registered as authorised. A family member
who is not registered can report a fault but cannot hear billing details.
""",
    ),
    "outages-and-compensation": (
        "Outages and automatic compensation",
        """
## 1. Checking for an outage
When broadband or mobile service is lost, we first check for a known outage in the customer's area. If there is
one, we tell the customer the expected fix time and do not open a separate fault ticket.

## 2. Automatic compensation
If a broadband service is completely lost for more than two full working days after a fault is reported, the
customer is entitled to automatic compensation of 9.33 per day until the service is restored. It appears on the
next bill without the customer having to ask.

## 3. Missed engineer appointments
If an engineer misses an appointment or cancels with less than 24 hours' notice, the customer receives 30.00
compensation, credited to the next bill.
""",
    ),
    "credits-and-refunds": (
        "Credits and refunds",
        """
## 1. Goodwill credits
Agents may apply a goodwill credit of up to 10.00 for a service failure or a mistake on our side. A credit above
10.00 needs a supervisor's approval; the customer is told the request is with a supervisor and will hear back
within two working days.

## 2. Billing errors
If a customer has been charged twice for the same item or charged for a service they had cancelled, the full
amount wrongly charged is refunded as a credit, whatever its size, once the error is confirmed on the bill. Credits
above 10.00 still need a supervisor's approval.

## 3. Refunds to a bank account
Credits are applied to the account. A refund to a bank account is only made when an account is closed with a
credit balance, within 10 working days.
""",
    ),
    "billing-and-payments": (
        "Bills and payments",
        """
## 1. When bills are issued
Bills are issued monthly, on the same day each month, and cover the month ahead for plans and the month just
ended for usage such as calls and roaming.

## 2. Late payment
A bill not paid within 14 days of its due date is overdue. We send a reminder, and after 28 days a late payment
fee of 5.00 is added. Service is never restricted without at least 7 days' written notice.

## 3. Payment arrangements
Customers who are struggling to pay can ask for a payment arrangement that spreads an overdue balance over up to
six months. No late payment fee is added while an arrangement is kept.
""",
    ),
    "broadband-faults": (
        "Broadband faults",
        """
## 1. Before opening a fault ticket
Ask the customer to restart the router, check that the cable from the wall socket is secure, and try a device
connected by cable. If there is a known outage in the area, do not open a fault ticket.

## 2. Opening a fault ticket
Open a fault ticket when the steps above do not restore the service. The network team responds within one working
day and books an engineer if the fault is in the line or the router.

## 3. Slow speeds
If speeds are below the minimum guaranteed speed in the contract for three days in a row, the customer may leave
the contract without a fee if the problem is not fixed within 30 days.
""",
    ),
    "moving-home": (
        "Moving home",
        """
## 1. Notice
Customers moving home should tell us at least 14 days before the move. We check whether the service is available
at the new address.

## 2. Contracts when moving
If we can provide the same service at the new address, the contract moves with the customer. If we cannot, the
contract ends without an early termination fee.

## 3. Setup at the new address
A home move is free once in a contract term. A second move in the same term costs 40.00.
""",
    ),
    "contracts-and-cancellation": (
        "Contracts and cancellation",
        """
## 1. Minimum terms
Broadband contracts run for 18 or 24 months; mobile contracts for 12 or 24 months. After the minimum term the
contract continues month to month.

## 2. Cancelling within the minimum term
Cancelling before the end of the minimum term costs the remaining monthly charges, less 15 percent. Cancelling
within 14 days of the start of a contract costs nothing.

## 3. Cancelling after the minimum term
After the minimum term a customer can cancel with 30 days' notice and no fee. Cancellation requests are handled by
a person: open a cancellation ticket or hand the call over.
""",
    ),
    "roaming": (
        "Using a mobile abroad",
        """
## 1. Europe
Roaming in Europe costs 2.50 per day on any plan and uses the plan's normal allowances.

## 2. Rest of the world
Outside Europe, data costs 6.00 per 100 MB. A text is sent when 50.00 of roaming charges is reached in a month,
and data stops at 100.00 unless the customer agrees to continue.
""",
    ),
    "complaints": (
        "Complaints",
        """
## 1. Making a complaint
Any expression of dissatisfaction that the customer wants us to act on is a complaint. Open a complaint ticket with
the customer's words and what they want to happen.

## 2. Timescales
We respond to a complaint within 5 working days. If a complaint is not resolved within 8 weeks, the customer can
take it to the independent ombudsman, free of charge.
""",
    ),
    "vulnerable-customers": (
        "Customers who need extra support",
        """
## 1. Recognising extra needs
If a customer tells us about a disability, illness, bereavement or financial difficulty, offer to note it on the
account so they do not have to explain again. Ask for consent before noting it.

## 2. Priority fault repair
Customers who depend on their line for a medical alarm or a disability get priority fault repair, with an engineer
within one working day.
""",
    ),
    "engineer-visits": (
        "Engineer visits",
        """
## 1. Booking
Engineer visits are booked in morning (8 to 1) or afternoon (1 to 6) slots. The customer or another adult must be at
home.

## 2. Charges
A visit is free when the fault is in our network or equipment. If the fault is caused by the customer's own wiring
or equipment, a charge of 65.00 applies, and the customer is told before the visit is booked.
""",
    ),
    "handing-over": (
        "When a person takes over",
        """
## 1. When to hand over
Hand the call to a person when the customer asks for one, when the customer is very upset, for cancellations, for a
bereavement, or when the agent cannot help after two attempts.

## 2. What the person receives
The person taking over sees the transcript, who the caller is (if checked) and what has been done so far, so the
customer does not have to repeat themselves.
""",
    ),
}

FERNHILL = {
    "identity-and-privacy": (
        "Identity checks",
        """
## 1. Before discussing an account
Confirm the account number or the phone number on the account, then the postcode and the date of birth of the
account holder. All three must match before any account details are given.

## 2. Failed checks
After three failed attempts, stop the check and ask the caller to use the online account or call back.
""",
    ),
    "supply-interruptions": (
        "Supply interruptions",
        """
## 1. Power cuts
Power cuts are handled by the regional network operator. Give the customer the national power cut number 105 and
check for known interruptions in their area.

## 2. Gas emergencies
If the customer smells gas, tell them to call the gas emergency line on 0800 111 999 immediately and end the call.
Do not troubleshoot a suspected gas leak.
""",
    ),
    "billing-and-payments": (
        "Energy bills",
        """
## 1. Estimated bills
Bills are estimated when no meter reading is received. A customer can give a reading at any time, and the next bill
is corrected.

## 2. Direct debit reviews
Direct debits are reviewed every six months. A customer can ask for a review sooner if their balance is more than
50.00 in credit.
""",
    ),
    "credits-and-refunds": (
        "Credits",
        """
## 1. Goodwill credits
Agents may apply a goodwill credit of up to 10.00. Larger credits need a supervisor.

## 2. Credit balances
A credit balance above 100.00 can be refunded to the customer's bank account on request within 10 working days.
""",
    ),
    "smart-meters": (
        "Smart meters",
        """
## 1. Installation
Smart meter installation is free and takes about two hours. Someone over 18 must be at home.

## 2. Readings
Smart meters send readings automatically every half hour. If no reading has arrived for 30 days, book a check.
""",
    ),
    "complaints": (
        "Complaints",
        """
## 1. Timescales
We respond within 5 working days. After 8 weeks the customer can go to the energy ombudsman free of charge.
""",
    ),
}
