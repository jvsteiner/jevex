## A new agent architecture

I now have Beta access to system1. Their new model called Jev is a new type of model that makes structured decisions rather than producing raw text. https://docs.typesafe.ai/introduction

### the idea
I'm trying to think about the architecture in an agent loop. like maybe you have this thing sitting side-saddle with an llm in an agent loop.  The state is the previous turns. instead of having the LLM make the tool calling decision you use Jev.  this way the LLM never sees tool JSON - it just sees the question, then waits for Jev to decide whether to call a tool, and which one. then, if the chosen tool requires an input, the LLM generates it. then we get a result - that goes to the state that they both see. Jev takes another decision. Basically Jev does all the deciding, and tells the LLM when to speak - it controls the agenda, while the LLM controls the content


### the conversation that followed
[9/17/26, 12:23:25] Joshua Bouw: Yep - and slots things into context when required.
[9/17/26, 12:23:37] Joshua Bouw: But the reasoning to use it should be LLM
[9/17/26, 12:24:07] Joshua Bouw: Possible to add as a capsule btw
[9/17/26, 12:24:14] Joshua Bouw: And have it inject whereveer the hell you want
[9/17/26, 12:24:28] Jamie Steiner: this is not my initial idea
[9/17/26, 12:24:32] Jamie Steiner: but i will experiment
[9/17/26, 12:26:06] Joshua Bouw: I mean, if Jev can do the tool calling decision that would be incredible.
[9/17/26, 12:27:02] Jamie Steiner: Yeah, that's my point.  I think that’s the premier spot inside the agent loop where jev could slot in.
[9/17/26, 12:27:11] Jamie Steiner: All of the decisions/
[9/17/26, 12:27:25] Jamie Steiner: LLM never decides - it just blabs
[9/17/26, 12:27:49] Jamie Steiner: its a little split personality
[9/17/26, 12:27:51] Joshua Bouw: Yeah this is like early Astrid shit I tried expirementing with.. well before I joined Unicity
[9/17/26, 12:28:01] Joshua Bouw: But for its memories too
[9/17/26, 12:28:07] Jamie Steiner: I also tried some shit like this with Otto previously
[9/17/26, 12:28:14] Joshua Bouw: IT was a different smaller LLM that would inject memories for the LLM to blab over


### the goal

Create a minimal agent using Python and LangChain to implement this idea.

#### requirements

needs to demonstrate effective tool calling and coordination between Jev and the LLM, with a reasonable amount of tools available. Probably some reasonable number of MCP's is required.

Needs to ensure minimal token use by LLM - never see's tool information. Zero decisions made by the LLM
