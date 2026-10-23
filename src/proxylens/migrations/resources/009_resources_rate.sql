-- One 60-second window per resource; start on its first admitted request.
CREATE UNIQUE INDEX resource_rate_scope ON resource_rate_windows(scope);
