# Demo statement - answer key

Built by `scripts/make_demo_statement.py`. Every row is synthetic. No real
account, card, phone number or person appears anywhere in it, and the file says
so on every page.

## Before you demo

```
python scripts/make_demo_statement.py                              # build it
python scripts/bootstrap_payee_reputation.py --demo-statement      # seed payees
python scripts/verify_demo_statement.py                            # check it
```

The verifier scores every row below through the real model and prints what a
judge will see. Run it the morning of the demo. It exits non-zero if anything
has moved.

The seeding step is not optional. A statement is one payer's side of every edge;
it cannot say how many *other* people paid an address or whether any came back,
and those two facts are what separate a busy shop from a collection account.
Without the seed the funnel account scores like any other new payee.

## What is in the file

- Period: the 92 days ending the day it was generated
- 288 rows over 27 pages: 269 ordinary, 19 planted
- Median ordinary payment: Rs 222
- Persona: salaried, pays rent monthly, buys groceries, takes cabs, has four
  friends who pay them back and an employer who pays them

The ordinary traffic is doing work, not filling pages. The engine scores a
payment against the payer's *own* history, so without three months of habits
none of the planted rows would stand out. Two choices in it matter:

- **The monthly rent is five figures.** So a large amount is normal for this
  payer, and F3 has to be caught on who is being paid and when, not on size.
- **Almost nothing happens at night.** Nine night-window rows in three months,
  and eight of them are the planted burst. That is what makes 02:14 loud.

## The planted rows

### F1 - Probe burst

**11 Sep 2026, 02:14 AM** &middot; 8 row(s) &middot; Rs 132

A credential being tested. Eight payments of Rs 1 to Rs 47 to eight addresses never paid before, inside 24 minutes, starting 02:14.

*What fires:* Transaction Scoring. Velocity, the night hour and an all-new payee set fire together. On the Network Graph these show as eight one-shot leaves appearing off the payer at once.

### F2 - Funnel account

**13 Sep 2026, 06:02 PM** &middot; 5 row(s) &middot; Rs 22,500

One address opened three days earlier takes 5 x Rs 4,500 in 44 minutes and sends nothing back.

*What fires:* The strongest catch in the file, and it comes entirely from the payee side: 42 other payers, none of whom returned, into an address three days old. The payer behaves normally throughout. This is the row to use when someone asks why the payee half of the model is there.

### F3 - Hijacked profile

**14 Sep 2026, 03:47 AM** &middot; 3 row(s) &middot; Rs 180,650

Rs 92,400 at 03:47 to an address never paid before - far above anything this payer sends, at an hour they have never used.

*What fires:* Transaction Scoring. Amount against the payer's own median, hour familiarity and an unseen payee. The amount also sits above 70% of the per-transaction ceiling, which the amount check reports separately.

### F4 - Victim-authorised transfer

**15 Sep 2026, 11:19 AM** &middot; 2 row(s) &middot; Rs 18,000

Rs 18,000 at 11:32 on an ordinary day, preceded by a Rs 1 credit from the same address thirteen minutes earlier - the refund-scam opening, a token payment to prove the 'refund' works before the real ask.

*What fires:* EXPECTED TO SCORE LOW, and worth showing for that reason. Nothing about the payment is unusual, because in this class nothing ever is: the payer authorised it themselves after being deceived. The report measures 28.6% recall here. What covers it is the payee check (address four days old, nine payers, none returning) and the coercion classifier if the message is pasted in.

### F5 - Lookalike bank handle

**16 Sep 2026, 07:21 PM** &middot; 1 row(s) &middot; Rs 47,500

Rs 47,500 to hdfcbank.refund@yb1. The handle is @yb1 with a digit one; the real handle is @ybl with a letter ell. In the face every payment app renders a VPA in, they are all but identical.

*What fires:* Payee Check scores this 100 on two separate critical findings: the confusable handle, and a bank's name paired with the word 'refund', which no bank handle does. The behavioural model cannot see any of it - no feature in the model reads the characters of an address.

## Suggested order for a demo

1. **Import the statement.** The payer profile builds from the ordinary traffic.
   Show the profile: median payment, usual hour, the handful of payees they
   actually deal with.
2. **Open the Network Graph.** The regular payees form a small dense core. F1's
   eight one-shot leaves and F2's funnel sit outside it and are visible without
   anyone explaining them.
3. **Score F3.** A strong, obvious catch. Good confidence-builder.
4. **Run F5's address through Payee Check.** Show @yb1 beside @ybl on screen and
   let the panel try to tell them apart. Then point out the model scored it on
   behaviour alone and never looked at the characters at all.
5. **Score F4 last, and say it scores low.** Then show the payee check and the
   coercion classifier picking it up. A panel told plainly where a system is
   weak, and shown the design that covers that weakness, will believe the parts
   that work. A panel that catches you overselling will not.

## Deliberately not in the file

- **An amount over the Rs 1,00,000 ceiling.** It cannot appear in a real
  statement because the rail rejects it before settlement. Demonstrate that
  check by typing Rs 1,50,000 into Transaction Scoring directly.
- **A scam message.** The coercion classifier takes pasted text, not statement
  rows. Paste something in the style of "your electricity will be disconnected
  tonight, pay now to avoid it" while F4 is on screen.

## If a judge asks whether the data is real

Say no, and say why: UPI transaction records identify both parties, so no
labelled public dataset exists and a real statement cannot be shown. The
generator is in the repository and its parameters are in the report. That answer
is stronger than a vague one, and it is the same limitation the report states in
its own results chapter.
