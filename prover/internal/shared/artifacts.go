package shared

import "os"

// CheckArtifacts ensures all required files exist and are non-empty.
func CheckArtifacts(paths []string) (bool, []string) {
	missing := make([]string, 0)
	for _, p := range paths {
		info, err := os.Stat(p)
		if err != nil || info.Size() == 0 {
			missing = append(missing, p)
		}
	}
	return len(missing) == 0, missing
}
