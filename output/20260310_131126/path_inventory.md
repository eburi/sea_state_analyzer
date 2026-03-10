# Signal K Path Inventory

*Generated 2026-03-10T13:12:26.310677+00:00*

## Summary

| Stat | Value |
|------|-------|
| Total paths observed | 215 |
| Expected paths present | 11 / 14 |

## Expected paths status

| Path | Present | Count | Recommended |
|------|---------|-------|-------------|
| `navigation.attitude` | ✓ | 1102 | yes |
| `navigation.attitude.roll` | ✗ | 0 | check substitutes |
| `navigation.attitude.pitch` | ✗ | 0 | check substitutes |
| `navigation.attitude.yaw` | ✗ | 0 | check substitutes |
| `navigation.rateOfTurn` | ✓ | 551 | yes |
| `navigation.speedOverGround` | ✓ | 384 | yes |
| `navigation.courseOverGroundTrue` | ✓ | 964 | yes |
| `navigation.headingTrue` | ✓ | 899 | yes |
| `environment.wind.speedTrue` | ✓ | 1282 | yes |
| `environment.wind.angleTrueWater` | ✓ | 1282 | yes |
| `environment.wind.speedApparent` | ✓ | 551 | yes |
| `environment.wind.angleApparent` | ✓ | 551 | yes |
| `navigation.position` | ✓ | 598 | yes |
| `navigation.datetime` | ✓ | 109 | yes |

## All observed self paths

| Path | Count | First seen | Last seen | Sources | Sample values |
|------|-------|-----------|-----------|---------|---------------|
| `environment.wind.directionTrue` | 1282 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 1.9931277076698684 / 1.9931277076698684 / 1.9931277076641174 |
| `environment.wind.speedTrue` | 1282 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 9.940043306509791 / 9.940043306509791 / 9.940043306509791 |
| `environment.wind.angleTrueWater` | 1282 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | -2.43314984767404 / -2.43314984767404 / -2.43314984767404 |
| `navigation.attitude` | 1102 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.204, can0.35 | {'yaw': -1.9448, 'pitch': -0.052, 'roll': -0.0198} / {'yaw': |
| `steering.rudderAngle` | 1102 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.128, can0.204 | 0.1234 / 0.1278 / 0.1278 |
| `navigation.headingMagnetic` | 1101 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.204 | 4.3384 / 4.3357 / 4.3357 |
| `environment.current.drift` | 989 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 0.42053109224382884 / 0.42053109224482993 / 0.42110453120083 |
| `environment.current.setTrue` | 989 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 0.03447238415007625 / 0.03447238409980713 / 0.01090002725286 |
| `environment.current.setMagnetic` | 989 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 6.229780135985754 / 6.229780135935485 / 6.2062077790942904 |
| `environment.current.driftImpact` | 989 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 0.42006065211192817 / 0.42006065211204247 / 0.42012622638558 |
| `navigation.courseOverGroundTrue` | 964 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4, can0.43, derived-data | 4.393 / 4.3445 / 4.3445 |
| `navigation.leewayAngle` | 934 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | None / None / None |
| `navigation.headingTrue` | 899 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 4.426277555343908 / 4.4262775553381575 / 4.4235775553381576 |
| `navigation.magneticVariation` | 600 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4, derived-data | 0.0879 / 0.08787755534390838 / 0.08787755533815732 |
| `navigation.position` | 598 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | {'longitude': -92.1145578, 'latitude': -8.016524} / {'longit |
| `navigation.courseOverGroundMagnetic` | 580 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | 4.2566225068589825 / 4.256622444661843 / 4.243622444661843 |
| `performance.leeway` | 552 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | -0.006902986060017094 / -0.006519486834460587 / -0.005137550 |
| `environment.wind.speedApparent` | 551 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.105 | 7.76 / 7.76 / 7.76 |
| `environment.wind.angleApparent` | 551 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.105 | -2.156285307179586 / -2.156285307179586 / -2.156285307179586 |
| `navigation.rateOfTurn` | 551 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.204 | -0.02627972 / -0.02621316 / -0.02643437 |
| `steering.autopilot.target.headingMagnetic` | 551 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.204 | 4.3387 / 4.3368 / 4.3335 |
| `navigation.magneticVariation.source` | 544 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | derived-data | WMM 2025 / WMM 2025 / WMM 2025 |
| `navigation.speedOverGround` | 384 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4, can0.43 | 3.54 / 3.68 / 3.72 |
| `navigation.speedThroughWater` | 276 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.35 | 3.26 / 3.3 / 3.37 |
| `navigation.speedThroughWaterReferenceType` | 276 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.35 | Paddle wheel / Paddle wheel / Paddle wheel |
| `environment.water.temperature` | 194 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.35 | 301.32 / 301.32 / 301.33 |
| `navigation.courseGreatCircle.nextPoint.position` | 117 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4, courseApi | {'longitude': -137.9650425, 'latitude': -7.9235597} / {'long |
| `navigation.courseGreatCircle.bearingTrackTrue` | 116 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | 4.653 / 4.653 / 4.653 |
| `navigation.courseGreatCircle.nextPoint.distance` | 116 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | 5042945 / 5042941 / 5042941 |
| `navigation.courseGreatCircle.nextPoint.bearingTrue` | 116 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | 4.6565 / 4.6565 / 4.6565 |
| `navigation.courseGreatCircle.nextPoint.velocityMadeGood` | 116 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | 3.41 / 3.5 / 3.5 |
| `navigation.courseGreatCircle.nextPoint.timeToGo` | 116 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | 1478868.582 / 1440839.594 / 1440839.572 |
| `navigation.courseGreatCircle.crossTrackError` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | -14561.9 / -14563.22 / -14563.22 |
| `steering.autopilot.state` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.204 | wind / wind / wind |
| `navigation.course.calcValues.calcMethod` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | GreatCircle / GreatCircle / GreatCircle |
| `navigation.course.calcValues.bearingTrackTrue` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 4.647161005580097 / 4.647161005580097 / 4.647161005580097 |
| `navigation.course.calcValues.bearingTrackMagnetic` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 4.735038234076584 / 4.735061005580097 / 4.735038560924005 |
| `navigation.course.calcValues.crossTrackError` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | -36224.24240792023 / -36224.96652945082 / -36225.66366035605 |
| `navigation.course.calcValues.previousPoint.distance` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 148389.72442754032 / 148391.63530672799 / 148393.61285687328 |
| `navigation.course.calcValues.distance` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 5046343.390700352 / 5046341.606569555 / 5046339.746745573 |
| `navigation.course.calcValues.bearingTrue` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 4.6557504855410246 / 4.655750637700626 / 4.655750787449634 |
| `navigation.course.calcValues.bearingMagnetic` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 4.743627714037512 / 4.743650637700626 / 4.743628342793542 |
| `navigation.course.calcValues.velocityMadeGood` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 3.4175808404611945 / 3.4227880682133924 / 3.503180642405175 |
| `navigation.course.calcValues.timeToGo` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 1476583.474 / 1474336.565 / 1440502.292 |
| `navigation.course.calcValues.estimatedTimeOfArrival` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 2026-03-27T15:21:12.974Z / 2026-03-27T14:43:47.065Z / 2026-0 |
| `navigation.course.calcValues.route.timeToGo` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | None / None / None |
| `navigation.course.calcValues.route.estimatedTimeOfArrival` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | None / None / None |
| `navigation.course.calcValues.route.distance` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | None / None / None |
| `navigation.course.calcValues.targetSpeed` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | None / None / None |
| `performance.velocityMadeGoodToWaypoint` | 111 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | course-provider | 3.4175808404611945 / 3.4227880682133924 / 3.503180642405175 |
| `navigation.datetime` | 109 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | 2026-03-10T13:11:30.50000Z / 2026-03-10T13:11:31.50000Z / 20 |
| `environment.current` | 109 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | {'setTrue': 3.9879, 'drift': 0.52} / {'setTrue': 3.6634, 'dr |
| `sensors.ais.class` | 58 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.43 | B / B / B |
| `navigation.currentRoute.name` | 56 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | Route / Route / Route |
| `navigation.currentRoute.waypoints` | 56 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | [{'name': 'ORIGIN', 'position': {'value': {'latitude': -7.86 |
| `navigation.gnss.satellitesInView` | 56 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.4 | {'count': 18, 'satellites': [{'id': 1, 'elevation': 0.6807,  |
| `entertainment.device.fusion1.state` | 56 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.10 | off / off / off |
| `steering.autopilot.target.windAngleApparent` | 56 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.204 | -2.1744853071795864 / -2.1744853071795864 / -2.1744853071795 |
| `navigation.trip.log` | 56 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.35 | 2469677 / 2469681 / 2469684 |
| `navigation.log` | 56 | 2026-03-10T13:11:31 | 2026-03-10T13:12:26 | can0.35 | 2469677 / 2469681 / 2469684 |
| `navigation.gnss.antennaAltitude` | 55 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | -5.4 / -5.8 / -6 |
| `navigation.gnss.satellites` | 55 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | 19 / 21 / 20 |
| `navigation.gnss.horizontalDilution` | 55 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | 0.57 / 0.54 / 0.55 |
| `navigation.gnss.geoidalSeparation` | 55 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | -8.89 / -8.89 / -8.89 |
| `navigation.gnss.type` | 55 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | GPS+SBAS/WAAS / GPS+SBAS/WAAS / GPS+SBAS/WAAS |
| `navigation.gnss.methodQuality` | 55 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | DGNSS fix / DGNSS fix / DGNSS fix |
| `navigation.gnss.integrity` | 55 | 2026-03-10T13:11:31 | 2026-03-10T13:12:25 | can0.4 | no Integrity checking / no Integrity checking / no Integrity |
| `environment.inside.temperature` | 12 | 2026-03-10T13:11:31 | 2026-03-10T13:12:21 | signalk-raspberry-pi-bme680.XX | 304.26 / 304.26 / 304.26 |
| `environment.inside.humidity` | 12 | 2026-03-10T13:11:31 | 2026-03-10T13:12:21 | signalk-raspberry-pi-bme680.XX | 0.67039 / 0.67081 / 0.66999 |
| `environment.inside.pressure` | 12 | 2026-03-10T13:11:31 | 2026-03-10T13:12:21 | signalk-raspberry-pi-bme680.XX | 101158 / 101164 / 101160 |
| `environment.inside.gas` | 12 | 2026-03-10T13:11:31 | 2026-03-10T13:12:21 | signalk-raspberry-pi-bme680.XX | 754504.5045045046 / 741229.977110376 / 750279.955207167 |
| `environment.inside.airquality` | 12 | 2026-03-10T13:11:31 | 2026-03-10T13:12:21 | signalk-raspberry-pi-bme680.XX | 303 / 306 / 304 |
| `` | 3 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | {'name': 'Primrose', 'mmsi': '538071881', 'communication': { |
| `electrical.displays.raymarine.helm1.brightness` | 3 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.0, can0.2, can0.4 | 0.45 / 0.69 / 0.76 |
| `notifications.ais.unknown113` | 3 | 2026-03-10T13:11:31 | 2026-03-10T13:12:17 | can0.43 | {'message': 'Unknown Seatalk Alarm 113', 'method': ['visual' |
| `navigation.courseRhumbline.nextPoint.position` | 2 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.4, courseApi | {'longitude': None, 'latitude': None} / {'longitude': -137.9 |
| `design.aisShipType` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | {'name': 'Sailing', 'id': 36} |
| `design.draft` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | {'maximum': 1.35} |
| `design.length` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | {'overall': 13.99} |
| `design.beam` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | 7.96 |
| `design.airHeight` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | 23.21 |
| `environment.depth.transducerToKeel` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | -0.55 |
| `sensors.gps.fromBow` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | defaults | 7 |
| `notifications.navigation.anchor` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | hoekens-anchor-alarm | {'state': 'normal', 'method': ['visual', 'sound'], 'message' |
| `design.bowAnchorRollerHeight` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | hoekens-anchor-alarm | 1 |
| `entertainment.device.fusion1.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | FusionPRIMROSE |
| `entertainment.device.fusion1.avsource.source11.track.length` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 0 |
| `entertainment.device.fusion1.avsource.source11.track.number` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 0 |
| `entertainment.device.fusion1.avsource.source11.track.totalTracks` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 0 |
| `entertainment.device.fusion1.avsource.source11.playbackState` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Paused |
| `entertainment.device.fusion1.avsource.source11.track.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 |  |
| `entertainment.device.fusion1.avsource.source11.track.artistName` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 |  |
| `entertainment.device.fusion1.avsource.source11.track.albumName` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 |  |
| `entertainment.device.fusion1.avsource.source11.track.elapsedTime` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 0 |
| `entertainment.device.fusion1.output.zone1.equalizer` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | {'bass': 0, 'mid': 0, 'treble': 0} |
| `entertainment.device.fusion1.output.zone2.equalizer` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | {'bass': 0, 'mid': 0, 'treble': 0} |
| `entertainment.device.fusion1.output.zone3.equalizer` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | {'bass': 0, 'mid': 0, 'treble': 0} |
| `entertainment.device.fusion1.output.zone4.equalizer` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | {'bass': 0, 'mid': 0, 'treble': 0} |
| `entertainment.device.fusion1.output.zone1.volume.master` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 11 |
| `entertainment.device.fusion1.output.zone2.volume.master` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 11 |
| `entertainment.device.fusion1.output.zone3.volume.master` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 11 |
| `entertainment.device.fusion1.output.zone4.volume.master` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | 0 |
| `entertainment.device.fusion1.output.zone1.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Zone 1 |
| `entertainment.device.fusion1.output.zone2.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Zone 2 |
| `entertainment.device.fusion1.output.zone3.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Zone 3 |
| `entertainment.device.fusion1.output.zone4.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Zone 4 |
| `entertainment.device.fusion1.avsource.source0.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | AM |
| `entertainment.device.fusion1.avsource.source1.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | FM |
| `entertainment.device.fusion1.avsource.source2.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | SiriusXM |
| `entertainment.device.fusion1.avsource.source3.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Aux1 |
| `entertainment.device.fusion1.avsource.source4.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Aux2 |
| `entertainment.device.fusion1.avsource.source5.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | USB |
| `entertainment.device.fusion1.avsource.source6.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | iPod |
| `entertainment.device.fusion1.avsource.source7.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | MTP |
| `entertainment.device.fusion1.avsource.source9.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | DAB |
| `entertainment.device.fusion1.avsource.source10.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | Optical |
| `entertainment.device.fusion1.avsource.source11.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | AirPlay |
| `entertainment.device.fusion1.avsource.source12.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | UPnP |
| `entertainment.device.fusion1.output.zone1.source` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | entertainment.device.fusion1.avsource.source11 |
| `entertainment.device.fusion1.output.zone2.source` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | entertainment.device.fusion1.avsource.source11 |
| `entertainment.device.fusion1.output.zone3.source` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | entertainment.device.fusion1.avsource.source11 |
| `entertainment.device.fusion1.output.zone4.source` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | entertainment.device.fusion1.avsource.source11 |
| `entertainment.device.fusion1.avsource.source8.name` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | BT |
| `entertainment.device.fusion1.output.zone1.isMuted` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | False |
| `entertainment.device.fusion1.output.zone2.isMuted` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | False |
| `entertainment.device.fusion1.output.zone3.isMuted` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | False |
| `entertainment.device.fusion1.output.zone4.isMuted` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.10 | False |
| `navigation.courseRhumbline.crossTrackError` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.4 | -0.22 |
| `notifications.navigation.course.perpendicularPassed` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | course-provider | {'state': 'normal', 'method': [], 'message': '', 'id': 'b424 |
| `notifications.chartplotter.unknown116` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.4 | {'message': 'Unknown Seatalk Alarm 116', 'method': ['visual' |
| `notifications.autopilot.PilotOffCourse` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.204 | {'message': 'Pilot Off Course', 'method': ['visual'], 'state |
| `navigation.courseGreatCircle.nextPoint.value.href` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | None |
| `navigation.courseGreatCircle.nextPoint.value.type` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | Location |
| `navigation.courseGreatCircle.nextPoint.arrivalCircle` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | 0 |
| `navigation.courseGreatCircle.activeRoute.href` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | None |
| `navigation.courseGreatCircle.activeRoute.startTime` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | 2026-03-10T01:39:53.593Z |
| `navigation.courseGreatCircle.previousPoint.position` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | {'longitude': -90.8318847, 'latitude': -7.6089722} |
| `navigation.courseGreatCircle.previousPoint.value.type` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | VesselPosition |
| `navigation.courseRhumbline.activeRoute.href` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | None |
| `navigation.courseRhumbline.activeRoute.startTime` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | 2026-03-10T01:39:53.593Z |
| `navigation.courseRhumbline.nextPoint.value.href` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | None |
| `navigation.courseRhumbline.nextPoint.value.type` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | Location |
| `navigation.courseRhumbline.nextPoint.arrivalCircle` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | 0 |
| `navigation.courseRhumbline.previousPoint.position` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | {'longitude': -90.8318847, 'latitude': -7.6089722} |
| `navigation.courseRhumbline.previousPoint.value.type` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | VesselPosition |
| `navigation.course.startTime` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | 2026-03-10T01:39:53.593Z |
| `navigation.course.targetArrivalTime` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | None |
| `navigation.course.activeRoute` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | None |
| `navigation.course.arrivalCircle` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | 0 |
| `navigation.course.previousPoint` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | courseApi | {'position': {'longitude': -90.8318847, 'latitude': -7.60897 |
| `navigation.course.nextPoint` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.4 | {'position': {'longitude': -137.9650425, 'latitude': -7.9235 |
| `notifications.instrument.AISDangerousTarget` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.2 | {'message': 'AIS Dangerous Target', 'method': ['visual'], 's |
| `steering.autopilot.autoTurn.state` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.204 | False |
| `steering.autopilot.hullType` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.204 | sailCatamaran |
| `notifications.chartplotter.unknown115` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.4 | {'message': 'Unknown Seatalk Alarm 115', 'method': ['visual' |
| `notifications.autopilot.PilotWindShift` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.204 | {'message': 'Pilot Wind Shift', 'method': ['visual'], 'state |
| `electrical.displays.raymarine.helm1.color` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.2 | day1 |
| `environment.depth.belowTransducer` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.35 | 95.55 |
| `environment.depth.belowKeel` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 95 |
| `environment.depth.belowSurface` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 96.35 |
| `noforeignland.sent_to_api` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | signalk-to-noforeignland | 2026-03-10T13:03:30.993Z |
| `noforeignland.sent_to_api_local` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | signalk-to-noforeignland | 3/10/2026, 8:03:30 AM |
| `sensors.ais.fromBow` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.43 | 12 |
| `sensors.ais.fromCenter` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | can0.43 | 0 |
| `noforeignland.status` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | signalk-to-noforeignland | Save: 8:11:27 AM | Transfer: 8:03:30 AM |
| `noforeignland.source` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | signalk-to-noforeignland | can0.4 |
| `noforeignland.status_boolean` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | signalk-to-noforeignland | 0 |
| `noforeignland.savepoint` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | signalk-to-noforeignland | 2026-03-10T13:11:27.064Z |
| `noforeignland.savepoint_local` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | signalk-to-noforeignland | 3/10/2026, 8:11:27 AM |
| `environment.moon.1.fraction` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 0.48 |
| `environment.moon.1.phase` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 0.76 |
| `environment.moon.1.phaseName` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | Waning Crescent |
| `environment.moon.1.angle` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 1.62 |
| `environment.moon.1.times.rise` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T05:47:36.521Z |
| `environment.moon.1.times.set` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T18:51:00.526Z |
| `environment.moon.1.times.alwaysUp` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | False |
| `environment.moon.1.times.alwaysDown` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | False |
| `environment.moon.fraction` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 0.58 |
| `environment.moon.phase` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 0.73 |
| `environment.moon.phaseName` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | Waning Gibbous |
| `environment.moon.angle` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 1.73 |
| `environment.moon.times.rise` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | None |
| `environment.moon.times.set` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T18:00:00.355Z |
| `environment.moon.times.alwaysUp` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | False |
| `environment.moon.times.alwaysDown` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | False |
| `environment.sun` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | day |
| `environment.mode` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | day |
| `environment.sunlight.times.1.sunrise` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T12:14:26.510Z |
| `environment.sunlight.times.1.sunriseEnd` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T12:16:35.975Z |
| `environment.sunlight.times.1.goldenHourEnd` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T12:42:05.464Z |
| `environment.sunlight.times.1.solarNoon` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T18:19:53.109Z |
| `environment.sunlight.times.1.goldenHour` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T23:57:40.753Z |
| `environment.sunlight.times.1.sunsetStart` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-12T00:23:10.243Z |
| `environment.sunlight.times.1.sunset` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-12T00:25:19.708Z |
| `environment.sunlight.times.1.dusk` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-12T00:46:15.405Z |
| `environment.sunlight.times.1.nauticalDusk` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-12T01:10:35.274Z |
| `environment.sunlight.times.1.night` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-12T01:34:57.550Z |
| `environment.sunlight.times.1.nadir` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T06:19:53.109Z |
| `environment.sunlight.times.1.nightEnd` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T11:04:48.667Z |
| `environment.sunlight.times.1.nauticalDawn` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T11:29:10.943Z |
| `environment.sunlight.times.1.dawn` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T11:53:30.812Z |
| `environment.sunlight.times.sunrise` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T12:14:29.414Z |
| `environment.sunlight.times.sunriseEnd` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T12:16:38.941Z |
| `environment.sunlight.times.goldenHourEnd` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T12:42:09.081Z |
| `environment.sunlight.times.solarNoon` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T18:20:09.435Z |
| `environment.sunlight.times.goldenHour` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T23:58:09.790Z |
| `environment.sunlight.times.sunsetStart` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T00:23:39.929Z |
| `environment.sunlight.times.sunset` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T00:25:49.457Z |
| `environment.sunlight.times.dusk` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T00:46:45.824Z |
| `environment.sunlight.times.nauticalDusk` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T01:11:06.634Z |
| `environment.sunlight.times.night` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-11T01:35:30.057Z |
| `environment.sunlight.times.nadir` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T06:20:09.435Z |
| `environment.sunlight.times.nightEnd` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T11:04:48.814Z |
| `environment.sunlight.times.nauticalDawn` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T11:29:12.237Z |
| `environment.sunlight.times.dawn` | 1 | 2026-03-10T13:11:31 | 2026-03-10T13:11:31 | derived-data | 2026-03-10T11:53:33.046Z |

## Notes

- Paths not listed above are not present in this vessel's Signal K stream.
- If expected paths are missing, check instrument connections on Signal K.
- Navigation.attitude may arrive as a compound object (roll/pitch/yaw together).
