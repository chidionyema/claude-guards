import sys
import datetime
import json
import os
import uuid

# Function to read configuration from bin/board-target
def read_config(config_path):
    config = {}
    try:
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {config_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading configuration file {config_path}: {e}", file=sys.stderr)
        sys.exit(1)
    return config

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/estate-broadcast.py <message>", file=sys.stderr)
        sys.exit(1)

    input_message = sys.argv[1]

    # Read configuration
    # Assuming bin/board-target is in the parent directory of scripts/estate-broadcast.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, '../bin/board-target')
    config = read_config(config_path)

    target_repo = config.get('repo')
    target_issue_number = int(config.get('issue')) if config.get('issue') else None
    dead_letter_file_path = os.path.expanduser(config.get('dead_letter'))
    comment_format_template = config.get('comment_format')

    if not all([target_repo, target_issue_number, dead_letter_file_path, comment_format_template]):
        print("Error: Missing configuration values in bin/board-target", file=sys.stderr)
        sys.exit(1)

    # Generate timestamp in ISO 8601 format with 'Z' for UTC
    timestamp = datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'

    # Generate an idempotency key
    idempotency_key = str(uuid.uuid4())
    
    # Default values for 'from', 'kind', and 'priority' as they are not provided in the input.
    # These can be made configurable if needed in the future.
    source = "system"
    kind_priority = "broadcast/info" # Example: "kind/priority"

    # Format the message using the template from config and embed idempotency key
    # The template is 'ts **from** (kind/priority): message'
    # We need to replace 'ts', 'from', 'kind/priority', and 'message'
    # For idempotency, we'll append the key to the message part.
    
    # This is a simple replacement. A more robust solution might involve a templating engine
    # but for the given format, direct string replacement is sufficient.
    formatted_message = comment_format_template.replace('ts', timestamp)
    formatted_message = formatted_message.replace('**from**', f"**{source}**")
    formatted_message = formatted_message.replace('(kind/priority)', f"({kind_priority})")
    # Append idempotency key to the message part
    formatted_message = formatted_message.replace('message', f"{input_message} (id:{idempotency_key})")

    try:
        # Attempt to post the comment using the provided API function
        # This assumes 'default_api' is an object with a 'comment_on_issue' method
        response = default_api.comment_on_issue(repo=target_repo, number=target_issue_number, body=formatted_message)
        print(f"Successfully posted comment to {target_repo}#{target_issue_number}. Response: {response}")
    except Exception as e:
        # Handle API call failure
        warning_message = f"ERROR: Failed to post comment to {target_repo}#{target_issue_number}. Message logged to dead-letter file. Error: {e}"
        print(warning_message, file=sys.stderr)
        
        # Prepare entry for the dead-letter log
        dead_letter_entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "repo": target_repo,
            "issue_number": target_issue_number,
            "original_message": input_message,
            "formatted_message": formatted_message,
            "idempotency_key": idempotency_key,
            "error": str(e)
        }
        
        # Attempt to log the failed message to the dead-letter file
        try:
            # Ensure the directory for the dead-letter file exists
            os.makedirs(os.path.dirname(dead_letter_file_path), exist_ok=True)
            with open(dead_letter_file_path, 'a') as f:
                f.write(json.dumps(dead_letter_entry) + '\n')
            print(f"Message successfully logged to {dead_letter_file_path}", file=sys.stderr)
        except Exception as log_e:
            # Critical error if logging to dead-letter file also fails
            print(f"CRITICAL ERROR: Failed to log message to dead-letter file {dead_letter_file_path}. Error: {log_e}", file=sys.stderr)

if __name__ == "__main__":
    main()