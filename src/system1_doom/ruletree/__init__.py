"""The rule tree: a second way for this package to play Doom.

Every decision is a walk down a tree of rules. At each node Jev is asked which of the children's conditions holds
now, or none; the deepest node reached gives the action. Rules are written one failure at a time by a rule writer
(Codex, Claude, or a person) in the soft loop: play until something goes wrong, write one rule Jev could have used,
check it by replaying the game, gate it on the training seeds, and add it as an exception to the node that
decided (Ripple-Down Rules). The engine plays and replays games and grades proposals; it never answers for Jev.
"""
