import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, TextSubstitution
from launch_ros.actions import Node


def generate_launch_description():
    bringup_dir = get_package_share_directory("smol_bringup")
    camera_dir = get_package_share_directory("camera")

    use_sim_time = LaunchConfiguration("use_sim_time")
    base_params = LaunchConfiguration("base_params")
    hardware_params = LaunchConfiguration("hardware_params")
    model_params = LaunchConfiguration("model_params")
    mode_params = LaunchConfiguration("mode_params")
    site_params = LaunchConfiguration("site_params")
    validation_params = LaunchConfiguration("validation_params")
    watchdog_params = LaunchConfiguration("watchdog_params")
    test_mode_params = LaunchConfiguration("test_mode_params")
    camera_namespace = LaunchConfiguration("camera_namespace")
    validation_mode = LaunchConfiguration("validation_mode")
    enable_chassis_bringup = LaunchConfiguration("enable_chassis_bringup")
    enable_chassis_driver = LaunchConfiguration("enable_chassis_driver")
    enable_camera = LaunchConfiguration("enable_camera")
    enable_speech = LaunchConfiguration("enable_speech")
    enable_vla = LaunchConfiguration("enable_vla")
    enable_keyboard = LaunchConfiguration("enable_keyboard")
    enable_debug = LaunchConfiguration("enable_debug")
    vla_python = LaunchConfiguration("vla_python")
    lerobot_src = LaunchConfiguration("lerobot_src")
    enable_mem_defrag = LaunchConfiguration("enable_mem_defrag")
    mem_defrag_script = LaunchConfiguration("mem_defrag_script")

    # install/smol_bringup/share/smol_bringup -> workspace root
    workspace_root = os.path.abspath(os.path.join(bringup_dir, "../../../../"))
    default_lerobot_src = os.path.join(workspace_root, "ref_code", "lerobot-main (SmolVLA)", "src")
    default_mem_defrag_script = os.path.join(workspace_root, "defrag_memory.sh")

    params = [
        base_params,
        hardware_params,
        model_params,
        mode_params,
        site_params,
        validation_params,
        watchdog_params,
        test_mode_params,
        {"use_sim_time": use_sim_time},
    ]

    chassis_bringup = Node(
        package="chassis",
        executable="ugv_bringup",
        name="chassis_bringup",
        output="screen",
        parameters=params,
        condition=IfCondition(enable_chassis_bringup),
    )

    chassis_driver = Node(
        package="chassis",
        executable="ugv_driver",
        name="chassis_driver",
        output="screen",
        parameters=params,
        condition=IfCondition(enable_chassis_driver),
    )

    speech_node = Node(
        package="speech",
        executable="speech_node",
        name="speech_node",
        output="screen",
        parameters=params,
    )

    # 默认在 conda 环境中拉起 VLA（可通过 vla_python 覆盖解释器路径）
    vla_bridge_node = ExecuteProcess(
        cmd=[
            vla_python,
            "-m",
            "vla.vla_bridge_node",
            "--ros-args",
            "--params-file",
            base_params,
            "--params-file",
            hardware_params,
            "--params-file",
            model_params,
            "--params-file",
            mode_params,
            "--params-file",
            site_params,
            "--params-file",
            validation_params,
            "--params-file",
            watchdog_params,
            "--params-file",
            test_mode_params,
            "-p",
            [TextSubstitution(text="use_sim_time:="), use_sim_time],
        ],
        name="vla_bridge_node",
        output="screen",
        additional_env={"LEROBOT_SRC": lerobot_src},
    )

    mem_defrag = ExecuteProcess(
        cmd=["bash", mem_defrag_script],
        output="screen",
        condition=IfCondition(enable_mem_defrag),
    )

    debug_node = Node(
        package="debug",
        executable="debug_node",
        name="debug_node",
        output="screen",
        # debug_node 不依赖 bringup 参数体系，仅透传 use_sim_time
        parameters=[{"use_sim_time": use_sim_time}],
    )

    debug_group = GroupAction(
        condition=IfCondition(enable_debug),
        actions=[TimerAction(period=1.0, actions=[debug_node])],
    )

    # keyboard_node 保留为 debug_node 的旧别名，已由 debug_group 取代

    keyboard_node = Node(
        package="debug",
        executable="debug_node",
        name="keyboard_node",
        output="screen",
        parameters=[{"use_sim_time": use_sim_time}],
    )

    keyboard_group = GroupAction(
        condition=IfCondition(enable_keyboard),
        actions=[TimerAction(period=1.0, actions=[keyboard_node])],
    )

    camera_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(camera_dir, "launch", "camera.launch.py")),
        launch_arguments={"namespace": camera_namespace}.items(),
    )

    camera_group = GroupAction(
        condition=IfCondition(enable_camera),
        actions=[TimerAction(period=2.0, actions=[camera_launch])],
    )

    speech_group = GroupAction(
        condition=IfCondition(enable_speech),
        actions=[TimerAction(period=2.0, actions=[speech_node])],
    )

    vla_group = GroupAction(
        condition=IfCondition(enable_vla),
        actions=[
            TimerAction(period=2.5, actions=[mem_defrag]),
            TimerAction(period=4.0, actions=[vla_bridge_node]),
        ],
    )

    validation_group = GroupAction(
        condition=IfCondition(validation_mode),
        actions=[
            LogInfo(msg="Validation mode enabled"),
            TimerAction(
                period=6.0,
                actions=[ExecuteProcess(cmd=["ros2", "node", "list"], output="screen")],
            ),
            TimerAction(
                period=7.0,
                actions=[ExecuteProcess(cmd=["ros2", "topic", "list"], output="screen")],
            ),
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("validation_mode", default_value="false"),
            DeclareLaunchArgument("enable_chassis_bringup", default_value="true"),
            DeclareLaunchArgument("enable_chassis_driver", default_value="true"),
            DeclareLaunchArgument("enable_camera", default_value="true"),
            DeclareLaunchArgument("enable_speech", default_value="true"),
            DeclareLaunchArgument("enable_vla", default_value="true"),
            DeclareLaunchArgument(
                "enable_mem_defrag",
                default_value=EnvironmentVariable("ENABLE_MEM_DEFRAG", default_value="false"),
                description="Run defrag_memory.sh before starting VLA",
            ),
            DeclareLaunchArgument(
                "mem_defrag_script",
                default_value=EnvironmentVariable(
                    "MEM_DEFRAG_SCRIPT", default_value=default_mem_defrag_script
                ),
                description="Path to memory defrag script",
            ),
            DeclareLaunchArgument(
                "vla_python",
                default_value=EnvironmentVariable(
                    "VLA_PYTHON", default_value="/home/jetson/miniforge3/envs/lerobot2/bin/python3"
                ),
                description="Python executable for VLA node (default: conda lerobot2)",
            ),
            DeclareLaunchArgument(
                "lerobot_src",
                default_value=EnvironmentVariable("LEROBOT_SRC", default_value=default_lerobot_src),
                description="LeRobot source path for VLA node",
            ),
            # keyboard 默认关闭，调试时手动开启，避免干扰正常推理
            DeclareLaunchArgument("enable_keyboard", default_value="false"),
            # debug_node 是升级后的新入口，包含键盘控制 + 摄像头流推送
            DeclareLaunchArgument("enable_debug", default_value="false"),
            DeclareLaunchArgument(
                "base_params", default_value=os.path.join(bringup_dir, "config", "base.yaml")
            ),
            DeclareLaunchArgument(
                "hardware_params", default_value=os.path.join(bringup_dir, "config", "hardware.yaml")
            ),
            DeclareLaunchArgument(
                "model_params", default_value=os.path.join(bringup_dir, "config", "model.yaml")
            ),
            DeclareLaunchArgument(
                "mode_params", default_value=os.path.join(bringup_dir, "config", "mode.yaml")
            ),
            DeclareLaunchArgument(
                "site_params", default_value=os.path.join(bringup_dir, "config", "site.yaml")
            ),
            DeclareLaunchArgument(
                "validation_params", default_value=os.path.join(bringup_dir, "config", "validation.yaml")
            ),
            DeclareLaunchArgument(
                "watchdog_params", default_value=os.path.join(bringup_dir, "config", "watchdog.yaml")
            ),
            DeclareLaunchArgument(
                "test_mode_params", default_value=os.path.join(bringup_dir, "config", "test_mode.yaml")
            ),
            DeclareLaunchArgument("camera_namespace", default_value="camera"),
            chassis_bringup,
            chassis_driver,
            camera_group,
            speech_group,
            vla_group,
            keyboard_group,
            debug_group,
            validation_group,
        ]
    )
