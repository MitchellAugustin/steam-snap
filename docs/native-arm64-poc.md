# Native ARM64 Steam Snap PoC

On my local Spark:
- Client is now able to upgrade on top of a pre-existing build with the fully emulated client and launches successfully
- Games are not automatically selecting the correct Proton 11 + FEX runtime, so they will crash if the user doesn't set this explicitly in the compat menu
- DLSS is not yet working with this approach

I do not recommend that other users try this yet - it is still very much a work in progress.
