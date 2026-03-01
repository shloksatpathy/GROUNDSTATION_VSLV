import numpy as np

class AltitudeKalman:
    def __init__(self, process_var=0.3, measurement_var=15.0):
        self.x = np.array([[0.0], [0.0]])
        self.P = np.eye(2) * 500
        self.Q = np.eye(2) * process_var
        self.R = np.array([[measurement_var]])
        self.H = np.array([[1, 0]])
        self.initialized = False

    def update(self, z, dt):
        if not self.initialized:
            self.x[0, 0] = z
            self.initialized = True

        F = np.array([[1, dt], [0, 1]])

        # Predict
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q

        # Update
        y = np.array([[z]]) - (self.H @ self.x)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)

        self.x = self.x + K @ y
        self.P = (np.eye(2) - K @ self.H) @ self.P

        return self.x[0, 0], self.x[1, 0]