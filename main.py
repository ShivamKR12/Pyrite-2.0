import math
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout
from kivy.app import App
from kivy.core.window import Window
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.resources import resource_find
from kivy.graphics.transformation import Matrix
from kivy.graphics.opengl import glEnable, glDisable, GL_DEPTH_TEST
from kivy.graphics import RenderContext, Callback, PushMatrix, PopMatrix, Translate, Rotate, Mesh, UpdateNormalMatrix, Color, Line, Ellipse, InstructionGroup
from kivy.properties import NumericProperty

CHUNK_SIZE = 16
RENDER_DISTANCE = 2

def get_height(gx, gz):
    h = int(8 + 4 * math.sin(gx * 0.15) + 3 * math.cos(gz * 0.15))
    return max(1, min(15, h))


class Chunk:
    def __init__(self, cx, cz):
        self.cx = cx
        self.cz = cz
        self.group = InstructionGroup()

        self.group.add(PushMatrix())
        self.group.add(Translate(self.cx * CHUNK_SIZE, 0, self.cz * CHUNK_SIZE))

        self.mesh = self.build_mesh()
        self.group.add(self.mesh)
        self.group.add(PopMatrix())

    def build_mesh(self):
        vertices = []
        indices = []
        idx = 0

        color_top    = (0.44, 0.66, 0.20, 1.0)
        color_bottom = (0.22, 0.17, 0.10, 1.0)
        color_left   = (0.81, 0.27, 0.28, 1.0)
        color_right  = (0.20, 0.39, 0.14, 1.0)
        color_back   = (0.82, 0.49, 0.17, 1.0)
        color_front  = (0.35, 0.49, 0.80, 1.0)

        def add_face(x, y, z, nx, ny, nz, col, p1, p2, p3, p4):
            nonlocal idx
            for p in (p1, p2, p3, p4):
                vertices.extend([x + p[0], y + p[1], z + p[2], nx, ny, nz, *col])
            indices.extend([idx, idx+1, idx+2, idx+2, idx+3, idx])
            idx += 4

        for x in range(CHUNK_SIZE):
            for z in range(CHUNK_SIZE):
                gx = (self.cx * CHUNK_SIZE) + x
                gz = (self.cz * CHUNK_SIZE) + z
                h = get_height(gx, gz)

                for y in range(h):
                    if y == h - 1:
                        add_face(x, y, z, 0, 1, 0, color_top, (0,1,1), (1,1,1), (1,1,0), (0,1,0))
                    if y == 0:
                        add_face(x, y, z, 0, -1, 0, color_bottom, (0,0,0), (1,0,0), (1,0,1), (0,0,1))

                    if get_height(gx-1, gz) <= y:
                        add_face(x, y, z, -1, 0, 0, color_left, (0,0,0), (0,0,1), (0,1,1), (0,1,0))
                    if get_height(gx+1, gz) <= y:
                        add_face(x, y, z, 1, 0, 0, color_right, (1,0,1), (1,0,0), (1,1,0), (1,1,1))
                    if get_height(gx, gz-1) <= y:
                        add_face(x, y, z, 0, 0, -1, color_back, (1,0,0), (0,0,0), (0,1,0), (1,1,0))
                    if get_height(gx, gz+1) <= y:
                        add_face(x, y, z, 0, 0, 1, color_front, (0,0,1), (1,0,1), (1,1,1), (0,1,1))

        return Mesh(
            vertices=vertices,
            indices=indices,
            fmt=[(b'v_pos', 3, 'float'), (b'v_normal', 3, 'float'), (b'v_color', 4, 'float')],
            mode='triangles',
        )


class Joystick(Widget):
    out_x = NumericProperty(0)
    out_y = NumericProperty(0)

    def __init__(self, **kwargs):
        super(Joystick, self).__init__(**kwargs)
        self.bind(pos=self.update_canvas, size=self.update_canvas, out_x=self.update_canvas, out_y=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.clear()
        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        radius = self.width / 2
        with self.canvas:
            Color(1, 1, 1, 0.3)
            Line(circle=(cx, cy, radius), width=2)
            Color(1, 1, 1, 0.8)
            Ellipse(pos=(cx - 15 + (self.out_x * radius), cy - 15 + (self.out_y * radius)), size=(30, 30))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.grab(self)
            self.update_joystick(touch)
            return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self.update_joystick(touch)
            return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self.out_x = 0; self.out_y = 0
            return True

    def update_joystick(self, touch):
        cx = self.x + self.width / 2
        cy = self.y + self.height / 2
        dx = touch.pos[0] - cx; dy = touch.pos[1] - cy
        dist = math.hypot(dx, dy)
        max_d = self.width / 2
        if dist > max_d:
            dx = (dx / dist) * max_d
            dy = (dy / dist) * max_d
        self.out_x = dx / max_d
        self.out_y = dy / max_d


class VoxelRenderer(Widget):
    def __init__(self, **kwargs):
        self.canvas = RenderContext(compute_normal_mat=True)
        self.canvas.shader.source = resource_find('simple.glsl')

        # Physics & Camera State
        self.cam_pos = [8.0, 25.0, 25.0] # Spawn a bit higher to drop in!
        self.pitch = -30.0
        self.yaw = 0.0
        self.vel_y = 0.0
        self.is_grounded = False
        self.fly_mode = False

        self.active_chunks = {}

        super(VoxelRenderer, self).__init__(**kwargs)
        
        with self.canvas:
            self.cb_setup = Callback(self.setup_gl_context)
            PushMatrix()
            self.rot_x = Rotate(self.pitch, 1, 0, 0)
            self.rot_y = Rotate(self.yaw, 0, 1, 0)
            self.trans = Translate(-self.cam_pos[0], -self.cam_pos[1], -self.cam_pos[2])
            UpdateNormalMatrix()

            self.world_layer = InstructionGroup()
            self.canvas.add(self.world_layer)
            
            PopMatrix()
            self.cb_reset = Callback(self.reset_gl_context)

        self.update_chunks()

    def setup_gl_context(self, *args):
        glEnable(GL_DEPTH_TEST)

    def reset_gl_context(self, *args):
        glDisable(GL_DEPTH_TEST)

    def update_chunks(self):
        cam_cx = int(self.cam_pos[0] // CHUNK_SIZE)
        cam_cz = int(self.cam_pos[2] // CHUNK_SIZE)

        needed_chunks = set()
        for dx in range(-RENDER_DISTANCE, RENDER_DISTANCE + 1):
            for dz in range(-RENDER_DISTANCE, RENDER_DISTANCE + 1):
                needed_chunks.add((cam_cx + dx, cam_cz + dz))

        for coords in list(self.active_chunks.keys()):
            if coords not in needed_chunks:
                self.world_layer.remove(self.active_chunks[coords].group)
                del self.active_chunks[coords]

        for coords in needed_chunks:
            if coords not in self.active_chunks:
                new_chunk = Chunk(coords[0], coords[1])
                self.active_chunks[coords] = new_chunk
                self.world_layer.add(new_chunk.group)
                break 

    def check_collision(self, pos):
        """AABB Collision Detection against Voxel Grid"""
        px, py, pz = pos
        # Define Camera Bounding Box (Radius 0.3, Height 1.6)
        min_x = px - 0.4
        max_x = px + 0.4
        min_y = py - 1.5 # Feet are 1.5 units below the camera's "eye"
        max_y = py + 0.5 # Top of head is 0.1 units above the eye
        min_z = pz - 0.4
        max_z = pz + 0.4

        # Check all whole integer blocks that intersect our bounding box
        for x in range(math.floor(min_x), math.floor(max_x) + 1):
            for z in range(math.floor(min_z), math.floor(max_z) + 1):
                terrain_h = get_height(x, z)
                for y in range(math.floor(min_y), math.floor(max_y) + 1):
                    # If the block's Y is below the terrain height, it is solid!
                    if y < terrain_h:
                        return True
        return False

    def jump(self):
        if self.is_grounded and not self.fly_mode:
            self.vel_y = 12.0
            self.is_grounded = False

    def update_camera(self, proj, dt, move_js, look_js):
        self.canvas['projection_mat'] = proj

        # 1. Looking (Yaw & Pitch)
        self.yaw -= look_js.out_x * dt * 80.0
        self.pitch += look_js.out_y * dt * 80.0
        self.pitch = max(-90.0, min(90.0, self.pitch))

        rad_yaw = math.radians(self.yaw)
        rad_pitch = math.radians(self.pitch)

        # 2. Movement Logic
        if self.fly_mode:
            # FREE FLY MODE
            speed = 25.0 * dt
            forward = move_js.out_y * speed
            strafe = move_js.out_x * speed

            f_x = -math.sin(rad_yaw) * math.cos(rad_pitch)
            f_y = math.sin(rad_pitch)
            f_z = -math.cos(rad_yaw) * math.cos(rad_pitch)

            s_x = math.cos(rad_yaw)
            s_z = -math.sin(rad_yaw)

            self.cam_pos[0] += (f_x * forward) + (s_x * strafe)
            self.cam_pos[1] += (f_y * forward)
            self.cam_pos[2] += (f_z * forward) + (s_z * strafe)

        else:
            # PHYSICAL BODY MODE (AABB Physics)
            speed = 10.0 * dt
            forward = move_js.out_y * speed
            strafe = move_js.out_x * speed

            # Lock the forward vector to the horizontal plane (ignore pitch)
            f_x = -math.sin(rad_yaw)
            f_z = -math.cos(rad_yaw)
            s_x = math.cos(rad_yaw)
            s_z = -math.sin(rad_yaw)

            dx = (f_x * forward) + (s_x * strafe)
            dz = (f_z * forward) + (s_z * strafe)

            # Apply Gravity
            self.vel_y -= 30.0 * dt
            self.vel_y = max(-30.0, self.vel_y) # Terminal velocity limit
            dy = self.vel_y * dt

            # Axis-by-Axis Collision Resolution
            # X-Axis
            self.cam_pos[0] += dx
            if self.check_collision(self.cam_pos):
                self.cam_pos[0] -= dx 

            # Y-Axis (Vertical)
            self.cam_pos[1] += dy
            self.is_grounded = False
            if self.check_collision(self.cam_pos):
                if dy < 0:
                    self.is_grounded = True # Hit the floor
                self.cam_pos[1] -= dy
                self.vel_y = 0.0 # Stop falling

            # Z-Axis
            self.cam_pos[2] += dz
            if self.check_collision(self.cam_pos):
                self.cam_pos[2] -= dz

        # Apply Transform
        self.rot_x.angle = -self.pitch
        self.rot_y.angle = -self.yaw
        self.trans.x = -self.cam_pos[0]
        self.trans.y = -self.cam_pos[1]
        self.trans.z = -self.cam_pos[2]

        self.update_chunks()


class GameUI(FloatLayout):
    def __init__(self, **kwargs):
        super(GameUI, self).__init__(**kwargs)

        self.renderer = VoxelRenderer()
        self.add_widget(self.renderer)

        # Controls
        self.left_joystick = Joystick(size_hint=(None, None), size=(220, 220), pos_hint={'x': 0.08, 'y': 0.08})
        self.right_joystick = Joystick(size_hint=(None, None), size=(220, 220), pos_hint={'right': 0.92, 'y': 0.08})

        # New UI Buttons
        self.jump_btn = Button(text="JUMP", size_hint=(None, None), size=(120, 100), pos_hint={'right': 0.92, 'y': 0.40})
        self.jump_btn.bind(on_press=self.on_jump_press)

        self.fly_toggle = ToggleButton(text="Physical Mode", size_hint=(None, None), size=(180, 50), pos_hint={'center_x': 0.5, 'top': 0.95})
        self.fly_toggle.bind(state=self.on_fly_toggle)

        self.add_widget(self.left_joystick)
        self.add_widget(self.right_joystick)
        self.add_widget(self.jump_btn)
        self.add_widget(self.fly_toggle)

        # Keyboard & Mouse Control State
        self._mouse_look = {'out_x': 0, 'out_y': 0}
        self._keyboard_move = {'out_x': 0, 'out_y': 0}
        self._keys_pressed = set()
        self._request_keyboard()
        self._mouse_grabbed = False

        # For FPS-style mouse look
        Window.bind(on_motion=self.on_motion)
        # Start with a visible cursor
        self.release_mouse()
        Clock.schedule_interval(self.update, 1 / 60.)

    def on_jump_press(self, instance):
        self.renderer.jump()

    def on_fly_toggle(self, instance, value):
        if value == 'down':
            self.renderer.fly_mode = True
            instance.text = "Free Fly Mode"
            self.jump_btn.opacity = 0.3 # Fade out jump button in fly mode
        else:
            self.renderer.fly_mode = False
            instance.text = "Physical Mode"
            self.jump_btn.opacity = 1.0

    def _request_keyboard(self):
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self, 'text')
        if self._keyboard.widget:
            # If it exists, this widget is a VKeyboard object which you can use
            # to change the keyboard layout.
            pass
        self._keyboard.bind(on_key_down=self._on_keyboard_down)
        self._keyboard.bind(on_key_up=self._on_keyboard_up)

    def _keyboard_closed(self):
        self._keyboard.unbind(on_key_down=self._on_keyboard_down)
        self._keyboard.unbind(on_key_up=self._on_keyboard_up)
        self._keyboard = None

    def _on_keyboard_down(self, keyboard, keycode, text, modifiers):
        key_str = keycode[1]
        self._keys_pressed.add(key_str)
        if key_str == 'spacebar':
            self.renderer.jump()
        elif key_str == 'escape':
            self.release_mouse()
        elif key_str == 'f':
            self.fly_toggle.state = 'down' if self.fly_toggle.state == 'normal' else 'normal'
        return True

    def _on_keyboard_up(self, keyboard, keycode):
        key_str = keycode[1]
        if key_str in self._keys_pressed:
            self._keys_pressed.remove(key_str)
        return True

    def grab_mouse(self):
        Window.set_system_cursor('none')
        Window.grab_mouse()
        self._mouse_grabbed = True

    def release_mouse(self):
        Window.set_system_cursor('arrow')
        Window.ungrab_mouse()
        self._mouse_grabbed = False

    def on_touch_down(self, touch):
        # Let UI elements handle their own touches first
        if super().on_touch_down(touch):
            return True
        # If the click is from a mouse, grab the cursor for FPS-style look
        if 'mouse' in touch.profile:
            self.grab_mouse()
        # If it's a touch event, use it for drag-to-look
        else:
            touch.grab(self)
            return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            # Invert Y for standard FPS controls
            self._mouse_look['out_x'] += touch.dpos[0] * 0.1
            self._mouse_look['out_y'] -= touch.dpos[1] * 0.1
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)

    def on_motion(self, window, etype, me):
        # This method is bound to the Window's on_motion event.
        # It receives the window, event type, and the motion event object.

        # Only process if the mouse is grabbed and it's a mouse move event
        if self._mouse_grabbed and etype == 'move' and 'mouse' in me.profile:
            # Use the delta x and y from the motion event for camera control
            self._mouse_look['out_x'] += me.dx * 0.1
            self._mouse_look['out_y'] -= me.dy * 0.1 # Invert Y for standard FPS controls
            return True # We've handled this event
        return super().on_motion(etype, me)

    def update(self, dt):
        asp = self.width / float(self.height)
        proj = Matrix().view_clip(-asp, asp, -1, 1, 1, 100, 1)

        # Combine Joystick and Keyboard inputs for movement
        self._keyboard_move['out_x'] = ('d' in self._keys_pressed) - ('a' in self._keys_pressed)
        self._keyboard_move['out_y'] = ('w' in self._keys_pressed) - ('s' in self._keys_pressed)
        
        combined_move = lambda: None # Simple object to hold attributes
        combined_move.out_x = self.left_joystick.out_x + self._keyboard_move['out_x']
        combined_move.out_y = self.left_joystick.out_y + self._keyboard_move['out_y']

        combined_look = lambda: None
        combined_look.out_x = self.right_joystick.out_x + self._mouse_look['out_x']
        combined_look.out_y = self.right_joystick.out_y + self._mouse_look['out_y']

        self.renderer.update_camera(proj, dt, combined_move, combined_look)
        self._mouse_look['out_x'] = 0; self._mouse_look['out_y'] = 0 # Reset mouse delta


class VoxelGame(App):
    def build(self):
        return GameUI()


if __name__ == "__main__":
    VoxelGame().run()
