# Neon-sim cyberpunk city

Neon-sim adds a rain-slicked corporate city: districts and security zones, surveillance
devices, hacking and intrusion, a street economy with heat and wanted levels, cybernetic
implants, and fixer missions with corporate intrigue. It leans on existing systems rather
than rebuilding them — districts use the core `RegionComponent`, money is the colony-sim
scrip resource stack, warrants and bounties reuse dagger-sim law state, and implants can be
hacked with the same intrusion tools as any terminal.

In Discord, prefix these commands with `!`.

This guide covers districts, surveillance, and hacking. For the street economy, cyberware,
and fixer jobs, see [Neon-sim streets, cyberware, and fixers](neon-streets-and-fixers.md).

## Districts, sites, and access

Cyberpunk sites sit inside districts (named regions). A site may be public, may demand a
security clearance, or may be a patrolled restricted area. Case a site first to read its
security before you commit:

```text
!case-location target_id="Arasaka lobby"
```

Enter a site you are cleared for (clearance level or a matching zone pass):

```text
!enter-district target_id="Arasaka lobby"
```

If you lack clearance the entry is denied. You can still slip in covertly, but an
unauthorized presence in a patrolled restricted area is caught on the next patrol sweep,
which trips the zone alarm. At a manned checkpoint you have three options:

```text
!show-credentials target_id="skybridge checkpoint"
!bribe-checkpoint target_id="skybridge checkpoint"
!sneak-through-checkpoint target_id="skybridge checkpoint"
```

Showing valid credentials or bribing the guard (with scrip) passes you openly; sneaking
slips a calm checkpoint quietly but fails against an alerted guard.

Claim a safehouse as your own base of operations:

```text
!claim-safehouse target_id="back-alley flop"
```

## Devices and surveillance

The city watches. Cameras, sensors, and drones with surveillance coverage record
unauthorized intruders that share their room, spawning evidence you will want gone.
Inspect a device to read its state:

```text
!inspect-device target_id="lobby camera"
```

Defeat surveillance *before* you trespass. Disabling cuts a camera entirely; looping feeds
it a fake signal so it appears live but records nothing; jamming knocks out a sensor:

```text
!disable-camera target_id="lobby camera"
!loop-camera target_id="lobby camera"
!jam-sensor target_id="motion sensor"
```

Sheltering in a site flagged as a blind spot also keeps you off the recording. Deploy a
drone to extend your own coverage:

```text
!deploy-drone target_id="recon drone"
```

If a camera already caught you, destroy the footage:

```text
!wipe-evidence target_id="lobby camera footage"
```

## Hacking and intrusion

Hackable devices — terminals, servers, electronic locks — have a security rating. Carry an
exploit tool whose power meets or beats that rating. Scan and trace a target first:

```text
!scan-network target_id="reception terminal"
!trace-network target_id="reception terminal"
```

Breach it by running an exploit, or — cleanly and silently — by using a matching credential:

```text
!run-exploit target_id="reception terminal"
!use-credential target_id="reception terminal"
```

A successful exploit starts a **counter-intrusion trace** counting down against you; a
failed one trips the local alarm. Once you are in, you can escalate privileges, install a
backdoor for silent future re-entry, open a session, steal data, sabotage the system, or
pop an electronic door:

```text
!escalate-privileges target_id="reception terminal"
!install-backdoor target_id="reception terminal"
!access-terminal target_id="reception terminal"
!exfiltrate-data target_id="records server"
!sabotage-system target_id="pump controller"
!unlock-door target_id="vault maglock"
```

Sensitive data needs admin privileges to exfiltrate. While a trace is live, shake it or buy
time before it lands and raises the alarm:

```text
!evade-trace
!spoof-identity
```

## Example run

```text
!case-location target_id="records office"
!loop-camera target_id="office camera"
!enter-district target_id="records office"
!run-exploit target_id="records server"
!escalate-privileges target_id="records server"
!exfiltrate-data target_id="records server"
!evade-trace
!wipe-evidence target_id="office camera footage"
```
