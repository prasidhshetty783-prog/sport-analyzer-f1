# LinkedIn post drafts

Pick whichever fits your voice. Plain text — paste straight into LinkedIn (it
keeps the line breaks). Swap in your own screenshot/GIF for reach.

---

## Version A — the full story (recommended)

I've been watching Formula 1 since 2014. Through the Mercedes era, the 2021
title fight that broke my heart and rebuilt it, the Sunday-afternoon alarms for
flyaway races — F1 has been a constant for me for over a decade.

So I finally built the thing I always wanted to exist: a real-time F1 race
dashboard that doesn't just show what's happening, but predicts what's about to.

🏎️ What it does:
• A live track map with every car moving in real time, built from real GPS data
• Live timing, tyres, gaps and pit stops
• And the part I'm most proud of — AI predictions for tyre life, pit windows,
  safety-car risk, and where each car will actually finish

The honest results (because numbers should mean something):
• Its finishing-position guess is on average within ~2 places of where a car
  really ends up. So if it says "P5", reality is usually P3–P7.
• It gets about 3 in 4 of its podium calls right while the race is still running.
• For safety cars: when it says there's roughly a 1-in-8 chance of one soon,
  that's about how often one actually appears — i.e. the percentages are honest,
  not vibes.

What I learned the hard way: in a sport this strategic, the live running order
is already a brutally good predictor. Beating it isn't about more data — it's
about modelling the chaos (safety cars, rain, DNFs). That reframing was the
whole project.

Built with Python, FastAPI, React and a Monte-Carlo simulation engine. Every
predicted number is labelled so it's never confused with real telemetry.

From fan to builder — easily the most fun I've had with a side project. 🏁

Repo + write-up in the comments. Would love feedback from other F1 + data folks.

#Formula1 #F1 #MachineLearning #DataScience #Python #React #SportsAnalytics

---

## Version B — short and punchy

Watching F1 since 2014. Building F1 tools since this week. 🏎️

I made a real-time race dashboard: a live GPS track map, live timing, and AI
that predicts tyre life, safety-car risk and final finishing positions as the
race runs.

In plain English, how well it works:
• Its finish prediction lands within ~2 positions of reality on average.
• It nails ~3 of every 4 podium calls mid-race.
• Its safety-car percentages are calibrated — when it says ~12%, ~13% actually
  happen.

The biggest lesson: in F1 the current order is already a great predictor, so the
real value isn't a single guess — it's modelling the chaos that flips a race.

Python + FastAPI + React + a Monte-Carlo engine. Fan project, all open data,
fully unofficial.

Link in comments 👇 #Formula1 #F1 #MachineLearning #DataScience

---

## Posting tips
- LinkedIn rewards a **visual** — drop in a screenshot or a short screen-capture
  GIF of the track map + predictions. Native video/GIF gets more reach than a link.
- Put the **repo link in the first comment**, not the body (the algorithm
  favours posts that keep people on-platform).
- The first 2 lines are the hook — they show before "…see more". Both versions
  front-load the 2014 line on purpose.
