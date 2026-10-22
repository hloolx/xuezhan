"""Measured mechanical motion shared by rigid vehicles and two-legged mechs.

Pure NumPy; no assets are created here. Coordinates are Blender metres (+X
forward, +Z up). The caller supplies actual pivots/radii/leg lengths. Root
translation is always zero; wheels, tread phase and leg support cancel the
gameplay move speed in their own local geometry.
"""
from __future__ import annotations

import math
import numpy as np


def smooth(value):
    t = min(1., max(0., float(value)))
    return t*t*(3-2*t)


def transform(rotation=None, location=None):
    result = np.eye(4)
    if rotation is not None:
        result[:3, :3] = rotation
    if location is not None:
        result[:3, 3] = location
    return result


def rotation(axis, angle):
    axis = np.asarray(axis, dtype=float)
    length = np.linalg.norm(axis)
    if length < 1e-8:
        raise ValueError("Measured axis has zero length")
    x, y, z = axis/length
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3)+math.sin(angle)*cross+(1-math.cos(angle))*(cross@cross)


def align(source, target):
    a, b = np.asarray(source, dtype=float), np.asarray(target, dtype=float)
    a, b = a/np.linalg.norm(a), b/np.linalg.norm(b)
    cross = np.cross(a, b)
    size = np.linalg.norm(cross)
    dot = float(np.clip(np.dot(a, b), -1, 1))
    if size < 1e-8:
        if dot > 0:
            return np.eye(3)
        perpendicular = np.cross(a, [1., 0, 0] if abs(a[0]) < .9 else [0., 0, 1.])
        return rotation(perpendicular, math.pi)
    return rotation(cross/size, math.atan2(size, dot))


def around(matrix, pivot):
    return transform(location=pivot) @ matrix @ transform(location=-np.asarray(pivot))


def capsule_length(half_straight, radius):
    if half_straight <= 0 or radius <= 0:
        raise ValueError("Actual tread path needs positive radius and straight span")
    return 4*half_straight+2*math.pi*radius


def capsule_frame(distance, half_straight, radius, lateral, centre_height, forward=0.):
    """Closed side-view tread loop, constant arclength; bottom tangent is +X."""
    length = capsule_length(half_straight, radius)
    s = distance % length
    straight, arc = 2*half_straight, math.pi*radius
    if s < straight:
        point, tangent = [-half_straight+s, lateral, centre_height-radius], [1, 0, 0]
    elif s < straight+arc:
        angle = -math.pi/2+(s-straight)/radius
        point = [half_straight+radius*math.cos(angle), lateral, centre_height+radius*math.sin(angle)]
        tangent = [-math.sin(angle), 0, math.cos(angle)]
    elif s < 2*straight+arc:
        point, tangent = [half_straight-(s-straight-arc), lateral, centre_height+radius], [-1, 0, 0]
    else:
        angle = math.pi/2+(s-2*straight-arc)/radius
        point = [-half_straight+radius*math.cos(angle), lateral, centre_height+radius*math.sin(angle)]
        tangent = [-math.sin(angle), 0, math.cos(angle)]
    point[0] += forward
    x = np.asarray(tangent)
    y = np.array([0., 1, 0])
    return transform(np.stack([x, y, np.cross(x, y)], axis=1), point)


def two_bone(hip, foot, upper_length, lower_length, pole):
    hip, foot, pole = map(lambda x: np.asarray(x, dtype=float), (hip, foot, pole))
    delta = foot-hip
    distance = np.linalg.norm(delta)
    if not abs(upper_length-lower_length)+1e-5 < distance < upper_length+lower_length-1e-5:
        raise ValueError("Measured leg cannot reach this target without stretching")
    direction = delta/distance
    perpendicular = pole-hip-direction*np.dot(pole-hip, direction)
    pole_length = np.linalg.norm(perpendicular)
    if pole_length < 1e-8:
        raise ValueError("Measured knee pole is collinear with hip/ankle")
    perpendicular /= pole_length
    along = (upper_length**2-lower_length**2+distance**2)/(2*distance)
    height = math.sqrt(max(0., upper_length**2-along**2))
    return hip+direction*along+perpendicular*height


def foot_path(time, cycle, speed, stance_fraction=.6, clearance=.18):
    """C1 support-to-swing joins; support foot velocity is exactly -speed."""
    phase = (time % cycle)/cycle
    support = cycle*stance_fraction
    half_stride = speed*support/2
    if phase < stance_fraction:
        return np.array([half_stride-speed*phase*cycle, 0, 0]), True
    t = (phase-stance_fraction)/(1-stance_fraction)
    swing_duration = cycle*(1-stance_fraction)
    # Cubic Hermite with matching endpoint velocities; no position pop.
    h00, h10 = 2*t**3-3*t*t+1, t**3-2*t*t+t
    h01, h11 = -2*t**3+3*t*t, t**3-t*t
    x = h00*(-half_stride)+h10*(-speed*swing_duration)+h01*half_stride+h11*(-speed*swing_duration)
    return np.array([x, 0, clearance*math.sin(math.pi*t)**2]), False


class Motion:
    """Bone-world delta matrices, applied to actual measured bind matrices."""
    def __init__(self, spec):
        self.spec = spec
        self.speed = float(spec["reference_move_speed_cm_s"])/100
        self.profile = spec["profile"]
        self.contact = float(spec["contact_time"])
        self.attack = float(spec["attack_interval"])
        self.origins = {name: np.asarray(point, dtype=float)/100 for name, point in spec["joint_origins_cm"].items()}
        if self.speed <= 0 or not 0 < self.contact < self.attack or not spec["recoil"]:
            raise ValueError("Positive movement speed, authoritative release and real recoil are required")
        if "root" not in self.origins or np.linalg.norm(self.origins["root"]) > 1e-8:
            raise ValueError("Mechanical root must be measured at the world origin")
        if self.profile == "wheeled_unit":
            wheels = spec["wheels"]
            if len(wheels) != 4:
                raise ValueError("ArmoredCar requires four actual wheels")
            radii = [w["radius_cm"]/100 for w in wheels]
            if min(radii) <= 0 or max(radii)/min(radii) > 1.01:
                raise ValueError("Normalize the actual wheel radii before a shared closed move cycle")
            self.cycle = 2*math.pi*sum(radii)/len(radii)/self.speed
            self.rolling_speed_relative_error = max(abs(radius/(sum(radii)/len(radii))-1) for radius in radii)
        elif self.profile == "tracked_unit":
            tracks = spec["tracks"]
            if len(tracks) != 2:
                raise ValueError("MainTank requires two actual tread paths")
            lengths = [capsule_length(t["half_straight_cm"]/100, t["radius_cm"]/100) for t in tracks]
            if abs(lengths[0]-lengths[1]) > .001:
                raise ValueError("Track loops need equal measured drive length")
            self.cycle = lengths[0]/self.speed
        elif self.profile == "biped_mech":
            if len(spec["legs"]) != 2:
                raise ValueError("Mech requires two measured hip/knee/ankle chains")
            self.cycle = float(spec.get("move_cycle", .9))
        else:
            raise ValueError("Unknown mechanical unit profile")
        self.durations = {"Idle": 2., "Move": self.cycle, "Attack": self.attack, "Hit": .5, "Death": 1.8}

    def recoil_kick(self, clip, time, recoil):
        """A short physical kick with an exact return to the ready pose."""
        elapsed = time-self.contact
        if clip != "Attack" or elapsed < 0:
            return 0.
        recovery = min(float(recoil.get("recovery", .24)), self.attack-self.contact)
        return smooth(elapsed/min(.025, recovery*.2))*(1-smooth(elapsed/recovery))

    def pose(self, clip, time):
        duration = self.durations[clip]
        time = min(max(float(time), 0), duration)
        death = smooth(time/(duration-.4)) if clip == "Death" else 0.
        hit = math.sin(math.pi*time/duration)**2 if clip == "Hit" else 0.
        moving = clip == "Move"
        bob = .012*math.sin(4*math.pi*time/self.cycle) if moving else (.004*math.sin(math.pi*time) if clip == "Idle" else 0.)
        if self.profile == "tracked_unit":
            bob = 0.  # The real fused undercarriage rests on the same tread plane.
        chassis = transform(rotation([1, 0, 0], math.radians(10*death-2*hit)),
                            [0, 0, bob-.035*death])
        result = {name: chassis.copy() for name in self.origins if name != "root"}
        result["root"] = np.eye(4)
        for name in self.spec.get("ground_bones", []):
            result[name] = chassis.copy() if clip == "Death" else np.eye(4)
        for recoil in self.spec["recoil"]:
            # The server owns release. This only moves the actual gun bone.
            kick = self.recoil_kick(clip, time, recoil)
            axis = np.asarray(recoil.get("axis", [-1., 0, 0]), dtype=float)
            axis /= np.linalg.norm(axis)
            point = self.origins[recoil["bone"]]
            delta = transform(location=axis*recoil["distance_cm"]/100*kick)
            droop = around(transform(rotation([0, 1, 0], math.radians(25*death))), point)
            result[recoil["bone"]] = chassis @ droop @ delta
            for dependent in recoil.get("dependent_bones", []):
                result[dependent] = result[recoil["bone"]]
        if self.profile == "wheeled_unit":
            # One complete physical revolution closes the baked cycle.
            for wheel in self.spec["wheels"]:
                name = wheel["bone"]
                result[name] = around(transform(rotation(wheel.get("axis", [0, 1, 0]),
                                          2*math.pi*time/self.cycle)), self.origins[name]) if moving else (
                                              chassis.copy() if clip == "Death" else np.eye(4))
        elif self.profile == "tracked_unit":
            for track in self.spec["tracks"]:
                args = (track["half_straight_cm"]/100, track["radius_cm"]/100,
                        track["lateral_cm"]/100, track["centre_height_cm"]/100,
                        track.get("forward_cm", 0)/100)
                length = capsule_length(args[0], args[1])
                for index, bone in enumerate(track["bones"]):
                    reference_phase = index*length/len(track["bones"])
                    ready = capsule_frame(reference_phase, *args)
                    actual = capsule_frame(reference_phase-length*time/self.cycle, *args) if moving else ready
                    result[bone] = (chassis if clip == "Death" else np.eye(4)) @ actual @ np.linalg.inv(ready)
        elif self.profile == "biped_mech":
            # Keep the two feet planted through idle/fire/hit/death. In Move,
            # only the swing foot lifts; the stance foot cancels actor velocity.
            body_shift = np.array([0., 0, -.36*death + (
                .025*math.sin(4*math.pi*time/self.cycle) if moving else .006*math.sin(math.pi*time) if clip == "Idle" else 0.)])
            chassis = transform(rotation([0, 1, 0], math.radians(32*death-6*hit)), body_shift)
            for name in result:
                if name != "root":
                    result[name] = chassis.copy()
            for index, leg in enumerate(self.spec["legs"]):
                hip, knee, ankle = [self.origins[leg[name]] for name in ("upper", "lower", "foot")]
                step = foot_path(time+index*self.cycle/2, self.cycle, self.speed,
                                 self.spec.get("stance_fraction", .6),
                                 self.spec.get("foot_clearance_cm", 18)/100)[0] if moving else np.zeros(3)
                actual_hip = (chassis @ np.r_[hip, 1])[:3]
                actual_ankle = ankle+step
                measured_pole = (chassis @ np.r_[knee, 1])[:3]
                actual_knee = two_bone(actual_hip, actual_ankle, np.linalg.norm(knee-hip),
                                       np.linalg.norm(ankle-knee), measured_pole)
                result[leg["upper"]] = transform(location=actual_hip) @ transform(align(knee-hip, actual_knee-actual_hip)) @ transform(location=-hip)
                result[leg["lower"]] = transform(location=actual_knee) @ transform(align(ankle-knee, actual_ankle-actual_knee)) @ transform(location=-knee)
                result[leg["foot"]] = transform(location=step)
            # Weapon recoil must remain visible for mech attacks too.
            for recoil in self.spec["recoil"]:
                kick = self.recoil_kick(clip, time, recoil)
                axis = np.asarray(recoil.get("axis", [-1., 0, 0]), dtype=float)
                delta = transform(location=axis/np.linalg.norm(axis)*recoil["distance_cm"]/100*kick)
                result[recoil["bone"]] = chassis @ delta
                for dependent in recoil.get("dependent_bones", []):
                    result[dependent] = result[recoil["bone"]]
        return result
