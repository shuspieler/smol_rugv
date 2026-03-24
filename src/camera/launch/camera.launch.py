import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('camera')
    param_file = os.path.join(pkg_dir, 'config', 'params.yaml')

    arg_namespace = DeclareLaunchArgument(
        name='namespace', default_value='camera',
        description='Namespace for the camera node (matches smol_bringup camera_namespace)',
    )

    camera_node = Node(
        package='camera',
        executable='camera_node',
        name='camera_node',
        namespace=LaunchConfiguration('namespace'),
        parameters=[param_file],
        output='screen',
    )

    return LaunchDescription([
        arg_namespace,
        camera_node,
    ])
